from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / "scripts/loadtest/aws/source_lineage.py"
SPEC = importlib.util.spec_from_file_location("aws_source_lineage", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class AwsSourceLineageTest(unittest.TestCase):
    def protected_fixture(self, root: Path) -> tuple[Path, Path]:
        protected_root = root / "protected-root"
        protected_file = protected_root / "evidence" / "old.json"
        protected_file.parent.mkdir(parents=True)
        protected_file.write_text('{"safe":true}\n', encoding="utf-8")
        manifest = root / "protected-manifest.json"
        write_json(manifest, {
            "schemaVersion": "aws-preexisting-evidence-protection-v1",
            "repositoryRoot": str(protected_root),
            "protectedRoot": "evidence",
            "fileCount": 1,
            "contentFingerprint": "0" * 64,
            "pathFingerprint": "1" * 64,
            "files": [{
                "path": "evidence/old.json",
                "sha256": hashlib.sha256(protected_file.read_bytes()).hexdigest(),
                "bytes": protected_file.stat().st_size,
                "mode": 0o644,
                "mtimeNs": protected_file.stat().st_mtime_ns,
                "inode": protected_file.stat().st_ino,
            }],
        })
        return manifest, protected_file

    def test_protected_manifest_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, protected_file = self.protected_fixture(root)
            MODULE.assert_protected_manifest_unchanged(manifest, ROOT)
            protected_file.write_text('{"tampered":true}\n', encoding="utf-8")
            with self.assertRaises(MODULE.SourceLineageError):
                MODULE.assert_protected_manifest_unchanged(manifest, ROOT)

    def test_new_output_path_rejects_existing_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, protected_file = self.protected_fixture(root)
            with self.assertRaises(MODULE.SourceLineageError):
                MODULE.assert_new_output_path(protected_file, repository_root=ROOT, protected_manifest=manifest)
            existing = root / "control.json"
            existing.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(MODULE.SourceLineageError):
                MODULE.assert_new_output_path(existing, repository_root=ROOT, protected_manifest=manifest)
            symlink = root / "link"
            symlink.symlink_to(root)
            with self.assertRaises(MODULE.SourceLineageError):
                MODULE.assert_new_output_path(symlink / "new.json", repository_root=ROOT, protected_manifest=manifest)

    def test_lineage_validation_recomputes_changed_files_and_digest(self):
        controller_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = self.protected_fixture(root)
            payload = {
                "schemaVersion": MODULE.LINEAGE_SCHEMA,
                "b01RunId": "aws-b01-fixture",
                "measurementSourceCommitSha": controller_sha,
                "controllerSourceCommitSha": controller_sha,
                "sourceDiff": {
                    "measurementSourceCommitSha": controller_sha,
                    "controllerSourceCommitSha": controller_sha,
                    "changedFiles": [],
                    "workloadInputPathsChecked": list(MODULE.WORKLOAD_INPUT_PREFIXES),
                    "workloadInputChanges": [],
                },
                "inputs": {},
                "protectedEvidenceManifestSha256": MODULE.sha256_file(manifest),
                "compatibility": {
                    "b01SeedBaselineSpikeCleanupRerunRequired": False,
                    "existingEvidenceRewriteRequired": False,
                },
            }
            payload["lineageSha256"] = MODULE.digest_json(payload)
            result = MODULE.validate_lineage(
                payload,
                repository_root=ROOT,
                expected_controller_sha=controller_sha,
                expected_run_id="aws-b01-fixture",
                expected_protected_manifest=manifest,
            )
            self.assertEqual(result["measurementSourceCommitSha"], controller_sha)
            payload["inputs"] = {
                "b01ProfileSha256": "a" * 64,
                "baselineCandidateSha256": "b" * 64,
                "d005RateRecordSha256": "c" * 64,
                "freezeInputDigest": "d" * 64,
            }
            payload.pop("lineageSha256", None)
            payload["lineageSha256"] = MODULE.digest_json(payload)
            MODULE.validate_lineage(
                payload,
                repository_root=ROOT,
                expected_controller_sha=controller_sha,
                expected_run_id="aws-b01-fixture",
                expected_protected_manifest=manifest,
                expected_inputs={key: value for key, value in payload["inputs"].items()},
            )
            tampered_inputs = json.loads(json.dumps(payload))
            tampered_inputs["inputs"]["d005RateRecordSha256"] = "e" * 64
            tampered_inputs.pop("lineageSha256", None)
            tampered_inputs["lineageSha256"] = MODULE.digest_json(tampered_inputs)
            with self.assertRaises(MODULE.SourceLineageError):
                MODULE.validate_lineage(
                    tampered_inputs,
                    repository_root=ROOT,
                    expected_controller_sha=controller_sha,
                    expected_run_id="aws-b01-fixture",
                    expected_protected_manifest=manifest,
                    expected_inputs={key: value for key, value in payload["inputs"].items()},
                )
            tampered = json.loads(json.dumps(payload))
            tampered["sourceDiff"]["changedFiles"] = ["load-tests/k6/aws/scenarios/baseline.js"]
            with self.assertRaises(MODULE.SourceLineageError):
                MODULE.validate_lineage(
                    tampered,
                    repository_root=ROOT,
                    expected_controller_sha=controller_sha,
                    expected_run_id="aws-b01-fixture",
                    expected_protected_manifest=manifest,
                )


if __name__ == "__main__":
    unittest.main()
