from __future__ import annotations

import json
import os
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts/loadtest/aws/bootstrap-load-runner-source.sh"
USER_DATA = ROOT / "infra/modules/load_test_runner/templates/runner-user-data.sh.tftpl"
K6_IMAGE = "grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755"
MOCK_IMAGE = "nginxinc/nginx-unprivileged:1.27.1-alpine3.20-perl@sha256:86b08eb3082f1f796f0ce1ef75a1c356a116fafc5f88754924fba2286fbd0221"


def run(command: list[str], cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=True, **kwargs)


class LoadRunnerBootstrapContractTests(unittest.TestCase):
    def test_base_user_data_defers_source_images_and_mock_to_staged_bootstrap(self) -> None:
        source = USER_DATA.read_text(encoding="utf-8")
        self.assertIn("base-ready.json", source)
        self.assertIn("command -v aws", source)
        self.assertIn("chmod 0600", source)
        self.assertNotIn("git clone", source)
        self.assertNotIn("git fetch", source)
        self.assertNotIn("docker pull", source)
        self.assertNotIn("runner-readiness.json", source)
        self.assertNotIn("GOOGLE_MOCK_IMAGE", source)

    def test_exact_commit_archive_is_shallow_remote_free_and_ignored_free(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scrum80-bootstrap-repo-") as repo_dir, tempfile.TemporaryDirectory(prefix="scrum80-bootstrap-evidence-") as evidence_dir:
            repo = Path(repo_dir)
            run(["git", "init", "-q"], repo)
            run(["git", "config", "user.email", "test@example.invalid"], repo)
            run(["git", "config", "user.name", "SCRUM-80 test"], repo)
            (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
            (repo / "tracked.txt").write_text("exact source\n", encoding="utf-8")
            (repo / "ignored").mkdir()
            (repo / "ignored/evidence.txt").write_text("must not be archived\n", encoding="utf-8")
            run(["git", "add", ".gitignore", "tracked.txt"], repo)
            run(["git", "commit", "-q", "-m", "fixture"], repo)
            source_sha = run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
            archive = Path(evidence_dir) / "source.tar.gz"
            completed = subprocess.run(
                [
                    "bash", str(BOOTSTRAP),
                    "--repository-root", str(repo),
                    "--source-commit", source_sha,
                    "--run-id", "bootstrap-contract",
                    "--region", "ap-northeast-2",
                    "--evidence-root", str(Path(evidence_dir) / "evidence"),
                    "--k6-image", K6_IMAGE,
                    "--mock-image", MOCK_IMAGE,
                    "--archive-output", str(archive),
                    "--dry-run",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            metadata = json.loads((Path(evidence_dir) / "evidence/aws/runner-source-bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "dry-run")
            self.assertEqual(metadata["sourceCommitSha"], source_sha)
            self.assertTrue(metadata["shallowClone"])
            self.assertTrue(metadata["remoteRemoved"])
            self.assertTrue(metadata["trackedOnly"])
            self.assertEqual(stat.S_IMODE((Path(evidence_dir) / "evidence/aws/runner-source-bootstrap.json").stat().st_mode), 0o600)
            with tarfile.open(archive, "r:gz") as bundle:
                names = bundle.getnames()
            self.assertTrue(any(name.endswith("tracked.txt") for name in names))
            self.assertTrue(any(name.endswith(".git/shallow") for name in names))
            self.assertFalse(any("ignored/" in name or "/evidence/" in name for name in names))

            with tempfile.TemporaryDirectory(prefix="scrum80-bootstrap-extract-") as extract_dir:
                with tarfile.open(archive, "r:gz") as bundle:
                    bundle.extractall(extract_dir)
                extracted = Path(extract_dir)
                self.assertEqual(run(["git", "rev-parse", "HEAD"], extracted).stdout.strip(), source_sha)
                self.assertEqual(run(["git", "remote"], extracted).stdout.strip(), "")
                self.assertEqual(run(["git", "rev-parse", "--is-shallow-repository"], extracted).stdout.strip(), "true")

    def test_bootstrap_has_private_s3_ssm_lineage_and_single_transient_retry(self) -> None:
        source = BOOTSTRAP.read_text(encoding="utf-8")
        for required in (
            "s3api put-object", "s3api head-object", "ssm send-command", "get-command-invocation",
            "source-commit-sha", "archive-sha256", "runner-readiness.json",
            "__SCRUM80_RUNNER_BOOTSTRAP_BEGIN__", "one same-byte transient retry",
            "rawOutputStored", "chmod 0600",
        ):
            self.assertIn(required, source)
        for forbidden in ("GITHUB_TOKEN", "ghp_", "BEGIN OPENSSH PRIVATE KEY", "public-read", "0.0.0.0/0"):
            self.assertNotIn(forbidden, source)

    def test_invalid_image_is_rejected_before_any_aws_call(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scrum80-bootstrap-evidence-") as evidence_dir:
            source_sha = run(["git", "rev-parse", "HEAD"], ROOT).stdout.strip()
            completed = subprocess.run(
                [
                    "bash", str(BOOTSTRAP),
                    "--repository-root", str(ROOT),
                    "--source-commit", source_sha,
                    "--run-id", "bootstrap-invalid-image",
                    "--region", "ap-northeast-2",
                    "--evidence-root", evidence_dir,
                    "--k6-image", "grafana/k6:latest",
                    "--dry-run",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("digest-pinned", completed.stderr)


if __name__ == "__main__":
    unittest.main()
