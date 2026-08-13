import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts/loadtest/seed-compose-load-data.py"
SPEC = importlib.util.spec_from_file_location("seed_compose_load_data", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SeedComposeLoadDataTest(unittest.TestCase):
    def test_opaque_token_matches_backend_format(self):
        token = MODULE.new_opaque_token()

        self.assertEqual(len(token), 43)
        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")

    def test_refresh_ttl_parser_supports_backend_duration_units(self):
        self.assertEqual(MODULE.parse_duration_ms("30d"), 30 * 24 * 60 * 60 * 1000)
        self.assertEqual(MODULE.parse_duration_ms("5m"), 5 * 60 * 1000)

    def test_rotated_cookie_parser_ignores_other_attributes(self):
        self.assertEqual(
            MODULE.ComposeSeed.rotated_cookie([
                "refresh_token=rotated-value; Path=/api/v1/auth; HttpOnly; SameSite=Lax",
            ]),
            "rotated-value",
        )
        self.assertIsNone(MODULE.ComposeSeed.rotated_cookie(["session=other; Path=/"]))

    def test_refresh_uses_cookie_contract_instead_of_authorization_header(self):
        runtime = object.__new__(MODULE.ComposeSeed)
        runtime.base_url = "http://example.test"
        captured = {}

        def fake_urlopen(request, payload, timeout):
            captured["authorization"] = request.headers.get("Authorization")
            captured["cookie"] = request.headers.get("Cookie")
            raise MODULE.URLError("test transport")

        original_urlopen = MODULE.urlopen
        MODULE.urlopen = fake_urlopen
        try:
            with self.assertRaises(MODULE.SeedError):
                runtime.api("POST", "/auth/token/refresh", refresh_cookie="refresh-token")
        finally:
            MODULE.urlopen = original_urlopen

        self.assertIsNone(captured["authorization"])
        self.assertEqual(captured["cookie"], "refresh_token=refresh-token")

    def test_credential_file_is_written_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            runtime = object.__new__(MODULE.ComposeSeed)
            runtime.write_credentials({"credentials": []}, path)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), stat.S_IRUSR | stat.S_IWUSR)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"credentials": []})


if __name__ == "__main__":
    unittest.main()
