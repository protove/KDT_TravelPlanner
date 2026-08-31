"""Static safety checks for the SCRUM-53 external Backend Secret bootstrap."""

from pathlib import Path
import base64
import json
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "eks" / "bootstrap-backend-secret.sh"


class BootstrapBackendSecretTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_is_valid(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_uses_fail_closed_cleanup_and_no_shell_tracing(self):
        self.assertIn("set -euo pipefail", self.source)
        self.assertIn("trap cleanup EXIT HUP INT TERM", self.source)
        self.assertNotIn("set -x", self.source)
        self.assertNotIn("--from-literal", self.source)

    def test_reads_exact_three_sources_and_only_declared_keys(self):
        self.assertEqual(self.source.count("secretsmanager get-secret-value"), 3)
        for key in (
            "SPRING_DATASOURCE_USERNAME",
            "SPRING_DATASOURCE_PASSWORD",
            "SPRING_DATA_REDIS_PASSWORD",
            "JWT_SECRET",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "NAVER_OAUTH_CLIENT_ID",
            "NAVER_OAUTH_CLIENT_SECRET",
            "GOOGLE_MAPS_API_KEY",
        ):
            self.assertIn(key, self.source)

    def test_secret_values_are_not_explicitly_printed(self):
        self.assertNotIn('cat "$tmp_dir/backend.json"', self.source)
        self.assertNotIn('echo "$', self.source)
        self.assertIn("Backend Secret applied", self.source)

    def test_generated_secret_preserves_all_nine_decoded_source_bytes(self):
        application = {
            "JWT_SECRET": "jwt \"quoted\"\\nline",
            "GOOGLE_OAUTH_CLIENT_ID": "google id with spaces",
            "GOOGLE_OAUTH_CLIENT_SECRET": "google\\secret$with`syntax",
            "NAVER_OAUTH_CLIENT_ID": "naver-id",
            "NAVER_OAUTH_CLIENT_SECRET": "naver\nsecret",
            "GOOGLE_MAPS_API_KEY": "maps: value\\with\\slashes",
        }
        database = {"username": "db-user", "password": "db-password\nwith-newline"}
        redis = {"password": "redis password with 'quotes'"}
        expected = {
            "SPRING_DATASOURCE_USERNAME": database["username"],
            "SPRING_DATASOURCE_PASSWORD": database["password"],
            "SPRING_DATA_REDIS_PASSWORD": redis["password"],
            "JWT_SECRET": application["JWT_SECRET"],
            "GOOGLE_OAUTH_CLIENT_ID": application["GOOGLE_OAUTH_CLIENT_ID"],
            "GOOGLE_OAUTH_CLIENT_SECRET": application["GOOGLE_OAUTH_CLIENT_SECRET"],
            "NAVER_OAUTH_CLIENT_ID": application["NAVER_OAUTH_CLIENT_ID"],
            "NAVER_OAUTH_CLIENT_SECRET": application["NAVER_OAUTH_CLIENT_SECRET"],
            "GOOGLE_MAPS_API_KEY": application["GOOGLE_MAPS_API_KEY"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            temp_root = root / "tmp"
            temp_root.mkdir()
            capture = root / "applied-secret.json"
            fake_aws = fake_bin / "aws"
            fake_aws.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                f"application = {json.dumps(application)!r}\n"
                f"database = {json.dumps(database)!r}\n"
                f"redis = {json.dumps(redis)!r}\n"
                "args = ' '.join(sys.argv)\n"
                "if 'secret:app' in args: print(application)\n"
                "elif 'secret:db' in args: print(database)\n"
                "elif 'secret:redis' in args: print(redis)\n"
                "else: raise SystemExit('unexpected secret source')\n",
                encoding="utf-8",
            )
            fake_kubectl = fake_bin / "kubectl"
            fake_kubectl.write_text(
                "#!/usr/bin/env python3\n"
                "import base64, json, os, sys\n"
                "args = sys.argv[1:]\n"
                "if 'create' in args and 'secret' in args:\n"
                "    data = {}\n"
                "    for arg in args:\n"
                "        if arg.startswith('--from-file='):\n"
                "            spec = arg[len('--from-file='):]\n"
                "            key, path = spec.split('=', 1)\n"
                "            data[key] = base64.b64encode(open(path, 'rb').read()).decode('ascii')\n"
                "    print(json.dumps({'metadata': {'name': 'backend-secret', 'namespace': 'travel-planner'}, 'data': data}))\n"
                "elif args and args[0] == 'apply':\n"
                "    with open(os.environ['FAKE_SECRET_CAPTURE'], 'wb') as output:\n"
                "        output.write(sys.stdin.buffer.read())\n"
                "else:\n"
                "    raise SystemExit('unexpected kubectl command')\n",
                encoding="utf-8",
            )
            for executable in (fake_aws, fake_kubectl):
                executable.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:app",
                    "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db",
                    "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:redis",
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "AWS_REGION": "ap-northeast-2",
                    "FAKE_SECRET_CAPTURE": str(capture),
                    "TMPDIR": str(temp_root),
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(capture.exists(), result.stdout + result.stderr)
            generated = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(set(generated["data"]), set(expected))
            for key, value in expected.items():
                self.assertEqual(base64.b64decode(generated["data"][key]), value.encode("utf-8"), key)
            combined_output = result.stdout + result.stderr
            for value in expected.values():
                self.assertNotIn(value, combined_output)
            self.assertEqual(list(temp_root.glob("travel-planner-secret.*")), [])


if __name__ == "__main__":
    unittest.main()
