from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/export-aws-capacity-stress-evidence.py"


class CapacityStressEvidenceExportTest(unittest.TestCase):
    def test_expected_fixture_exclusion_is_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "summary.json").write_text('{"status":"ok"}\n', encoding="utf-8")
            (root / "data.json").write_text('{"password":"never-export"}\n', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(root)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "capacity-evidence-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["privacyScan"], "PASS")
            self.assertIn("data.json", [item["path"] for item in manifest["excluded"]])
            self.assertNotIn("data.json", [item["path"] for item in manifest["files"]])

    def test_sensitive_exportable_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "summary.json").write_text('{"password":"leaked"}\n', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(root)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            manifest = json.loads((root / "capacity-evidence-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["privacyScan"], "FAIL")
            self.assertEqual(manifest["files"], [])


if __name__ == "__main__":
    unittest.main()
