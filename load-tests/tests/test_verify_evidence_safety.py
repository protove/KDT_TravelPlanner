import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load(module_name: str, relative_path: str):
    script_path = Path(__file__).parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SAFETY = _load("verify_evidence_safety", "scripts/loadtest/verify-evidence-safety.py")


class ScanTest(unittest.TestCase):
    def test_clean_bundle_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data.json").write_text(json.dumps({"credentials": [{"userId": "user-0000001"}]}), encoding="utf-8")
            (root / "metadata.json").write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")
            result = SAFETY.scan(root, root / "data.json")
            self.assertTrue(result["safe"])
            self.assertEqual(result["findingCount"], 0)

    def test_data_json_is_never_scanned_against_itself(self):
        # Regression test: data.json's own secret_values (its accessToken/
        # refreshToken/refreshFamilyId/userId) will always appear inside
        # data.json itself. Before the data.json exclusion, every bundle
        # containing this file would fail the safety scan unconditionally.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_file = root / "data.json"
            data_file.write_text(json.dumps({
                "credentials": [{"userId": "user-0000001", "refreshToken": "a-very-long-refresh-token-value"}],
            }), encoding="utf-8")
            (root / "metadata.json").write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")

            result = SAFETY.scan(root, data_file)

            self.assertTrue(result["safe"])
            self.assertEqual(result["findingCount"], 0)
            self.assertNotIn(str(data_file), [finding["file"] for finding in result["findings"]])

    def test_leaked_refresh_token_in_a_real_evidence_file_is_still_caught(self):
        # The data.json exclusion must not blind the scanner to a genuine
        # leak of the same secret value into some other file.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_file = root / "data.json"
            data_file.write_text(json.dumps({
                "credentials": [{"userId": "user-0000001", "refreshToken": "a-very-long-refresh-token-value"}],
            }), encoding="utf-8")
            (root / "k6").mkdir()
            (root / "k6" / "raw.json").write_text('{"leaked": "a-very-long-refresh-token-value"}', encoding="utf-8")

            result = SAFETY.scan(root, data_file)

            self.assertFalse(result["safe"])
            self.assertEqual(result["findingCount"], 1)
            self.assertTrue(result["findings"][0]["file"].endswith("k6/raw.json") or result["findings"][0]["file"].endswith("k6" + __import__("os").sep + "raw.json"))

    def test_forbidden_authorization_header_pattern_is_caught(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_file = root / "data.json"
            data_file.write_text('{"credentials": []}', encoding="utf-8")
            (root / "notes.txt").write_text("Authorization: Bearer abcdefghijklmnop", encoding="utf-8")

            result = SAFETY.scan(root, data_file)

            self.assertFalse(result["safe"])
            finding_types = {finding["type"] for finding in result["findings"]}
            self.assertIn("authorization_header", finding_types)
            self.assertIn("bearer_token", finding_types)


if __name__ == "__main__":
    unittest.main()
