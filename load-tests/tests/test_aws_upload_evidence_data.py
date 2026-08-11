import base64
import hashlib
import importlib.util
import json
import subprocess
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


UPLOAD = _load("upload_aws_evidence", "scripts/loadtest/aws/upload-aws-evidence.py")


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class VerifyAccountTest(unittest.TestCase):
    def test_rejects_non_12_digit_expected_id(self):
        with self.assertRaises(UPLOAD.UploadError):
            UPLOAD.verify_account("12345", "ap-northeast-2")

    def test_raises_without_leaking_account_ids(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout="999999999999\n")
        try:
            with self.assertRaises(UPLOAD.UploadError) as ctx:
                UPLOAD.verify_account("111111111111", "ap-northeast-2")
            self.assertNotIn("999999999999", str(ctx.exception))
            self.assertNotIn("111111111111", str(ctx.exception))
        finally:
            subprocess.run = original_run

    def test_passes_on_exact_match(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout="111111111111\n")
        try:
            UPLOAD.verify_account("111111111111", "ap-northeast-2")  # must not raise
        finally:
            subprocess.run = original_run


class ChecksumHelpersTest(unittest.TestCase):
    def test_sha256_of_file_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_bytes(b'{"hello": "world"}')
            digest, size = UPLOAD.sha256_of_file(path)
            self.assertEqual(digest, hashlib.sha256(b'{"hello": "world"}').hexdigest())
            self.assertEqual(size, len(b'{"hello": "world"}'))

    def test_hex_to_base64_matches_known_value(self):
        digest = hashlib.sha256(b"abc").hexdigest()
        expected = base64.b64encode(hashlib.sha256(b"abc").digest()).decode("ascii")
        self.assertEqual(UPLOAD.hex_to_base64(digest), expected)


class ManifestTest(unittest.TestCase):
    def test_iter_bundle_files_skips_manifest_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text("{}", encoding="utf-8")
            (root / "manifest.json").write_text("{}", encoding="utf-8")
            names = {path.name for path in UPLOAD.iter_bundle_files(root)}
            self.assertEqual(names, {"metadata.json"})

    def test_build_manifest_contains_sha256_and_bytes_for_every_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "k6").mkdir()
            (root / "k6" / "summary.json").write_text("{}", encoding="utf-8")
            (root / "metadata.json").write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")

            manifest = UPLOAD.build_manifest(root, "aws-b01-20260809-001")

            self.assertEqual(manifest["runId"], "aws-b01-20260809-001")
            self.assertEqual(manifest["fileCount"], 2)
            paths = {entry["path"] for entry in manifest["files"]}
            self.assertEqual(paths, {"metadata.json", "k6/summary.json"})
            for entry in manifest["files"]:
                self.assertEqual(len(entry["sha256"]), 64)
                self.assertGreater(entry["bytes"], 0)


class MetadataRunIdTest(unittest.TestCase):
    def test_passes_when_metadata_json_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            UPLOAD.check_metadata_run_id(Path(directory), "aws-b01-20260809-001")  # must not raise

    def test_passes_when_run_id_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({"runId": "aws-b01-20260809-001"}), encoding="utf-8")
            UPLOAD.check_metadata_run_id(root, "aws-b01-20260809-001")  # must not raise

    def test_raises_when_run_id_mismatched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({"runId": "other-run"}), encoding="utf-8")
            with self.assertRaises(UPLOAD.UploadError):
                UPLOAD.check_metadata_run_id(root, "aws-b01-20260809-001")


class SafetyScanTest(unittest.TestCase):
    def test_run_safety_scan_writes_report_and_returns_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_module = type("FakeSafety", (), {
                "scan": staticmethod(lambda evidence_root, data_file: {
                    "evidenceRoot": str(evidence_root), "scannedFiles": 1,
                    "findingCount": 0, "findings": [], "safe": True,
                })
            })

            result = UPLOAD.run_safety_scan(fake_module, root, Path(directory) / "data.json")

            self.assertTrue(result["safe"])
            report_path = root / UPLOAD.SAFETY_REPORT_FILENAME
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), result)

    def test_load_safety_scanner_exposes_scan_function(self):
        module = UPLOAD.load_safety_scanner()
        self.assertTrue(callable(module.scan))


class UploadFileTest(unittest.TestCase):
    def test_raises_on_checksum_mismatch(self):
        original_run = UPLOAD.run
        UPLOAD.run = lambda command: json.dumps({"ChecksumSHA256": "not-the-real-checksum"})
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "file.json"
                path.write_text("{}", encoding="utf-8")
                digest, _ = UPLOAD.sha256_of_file(path)
                with self.assertRaises(UPLOAD.UploadError):
                    UPLOAD.upload_file("bucket", "key", path, digest)
        finally:
            UPLOAD.run = original_run

    def test_passes_when_checksum_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.json"
            path.write_text("{}", encoding="utf-8")
            digest, _ = UPLOAD.sha256_of_file(path)
            expected_checksum = UPLOAD.hex_to_base64(digest)

            original_run = UPLOAD.run
            UPLOAD.run = lambda command: json.dumps({"ChecksumSHA256": expected_checksum})
            try:
                UPLOAD.upload_file("bucket", "key", path, digest)  # must not raise
            finally:
                UPLOAD.run = original_run

    def test_raises_when_checksum_missing_from_response(self):
        original_run = UPLOAD.run
        UPLOAD.run = lambda command: json.dumps({})
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "file.json"
                path.write_text("{}", encoding="utf-8")
                digest, _ = UPLOAD.sha256_of_file(path)
                with self.assertRaises(UPLOAD.UploadError):
                    UPLOAD.upload_file("bucket", "key", path, digest)
        finally:
            UPLOAD.run = original_run


class UploadBundleTest(unittest.TestCase):
    def test_raises_if_file_changed_after_manifest_built(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "metadata.json"
            target.write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")
            manifest = UPLOAD.build_manifest(root, "aws-b01-20260809-001")

            target.write_text('{"runId": "tampered"}', encoding="utf-8")

            original_run = UPLOAD.run
            UPLOAD.run = lambda command: json.dumps({"ChecksumSHA256": "irrelevant"})
            try:
                with self.assertRaises(UPLOAD.UploadError):
                    UPLOAD.upload_bundle(root, "aws-b01-20260809-001", "bucket", "evidence/aws-load-tests", manifest)
            finally:
                UPLOAD.run = original_run

    def test_uploads_every_file_plus_manifest_last(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")
            (root / "k6").mkdir()
            (root / "k6" / "summary.json").write_text("{}", encoding="utf-8")
            manifest = UPLOAD.build_manifest(root, "aws-b01-20260809-001")
            manifest_path = root / UPLOAD.MANIFEST_FILENAME
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            uploaded_keys = []

            def fake_upload_file(bucket, key, local_path, expected_sha256_hex):
                uploaded_keys.append(key)

            original_upload_file = UPLOAD.upload_file
            UPLOAD.upload_file = fake_upload_file
            try:
                count = UPLOAD.upload_bundle(root, "aws-b01-20260809-001", "bucket", "evidence/aws-load-tests", manifest)
            finally:
                UPLOAD.upload_file = original_upload_file

            self.assertEqual(count, 3)
            self.assertEqual(uploaded_keys[-1], "evidence/aws-load-tests/aws-b01-20260809-001/manifest.json")
            self.assertIn("evidence/aws-load-tests/aws-b01-20260809-001/metadata.json", uploaded_keys)
            self.assertIn("evidence/aws-load-tests/aws-b01-20260809-001/k6/summary.json", uploaded_keys)


if __name__ == "__main__":
    unittest.main()
