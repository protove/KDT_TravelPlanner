import base64
import hashlib
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


MANIFEST = _load("build_evidence_manifest", "scripts/loadtest/aws/build-evidence-manifest.py")


class ChecksumHelpersTest(unittest.TestCase):
    def test_sha256_of_file_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_bytes(b'{"hello": "world"}')
            digest, size = MANIFEST.sha256_of_file(path)
            self.assertEqual(digest, hashlib.sha256(b'{"hello": "world"}').hexdigest())
            self.assertEqual(size, len(b'{"hello": "world"}'))

    def test_hex_to_base64_matches_known_value(self):
        digest = hashlib.sha256(b"abc").hexdigest()
        expected = base64.b64encode(hashlib.sha256(b"abc").digest()).decode("ascii")
        self.assertEqual(MANIFEST.hex_to_base64(digest), expected)


class ClassifySourceTest(unittest.TestCase):
    def test_s3_download_is_the_default(self):
        self.assertEqual(MANIFEST.classify_source("metadata.json"), "s3-download")
        self.assertEqual(MANIFEST.classify_source("k6/summary.json"), "s3-download")
        self.assertEqual(MANIFEST.classify_source("aws/target-health.json"), "s3-download")

    def test_grafana_files_are_derived(self):
        self.assertEqual(MANIFEST.classify_source("grafana/dashboard.json"), "grafana-export")
        self.assertEqual(MANIFEST.classify_source("grafana/queries/panel-2-A.json"), "grafana-export")

    def test_safety_report_is_generated_locally(self):
        self.assertEqual(MANIFEST.classify_source("evidence-safety.json"), "generated-locally")


class IterBundleFilesTest(unittest.TestCase):
    def test_skips_manifest_json_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text("{}", encoding="utf-8")
            (root / "manifest.json").write_text("{}", encoding="utf-8")
            names = {p.name for p in MANIFEST.iter_bundle_files(root)}
            self.assertEqual(names, {"metadata.json"})


class DeterminePngStatusTest(unittest.TestCase):
    def test_not_exported_when_no_panels_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = MANIFEST.determine_png_status(Path(directory))
            self.assertEqual(result["pngStatus"], "not-exported")
            self.assertIn("D-003", result["pngStatusReason"])

    def test_not_exported_uses_status_json_reason_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            (panels_dir / "status.json").write_text(json.dumps({"status": "not-collected", "reason": "custom reason"}), encoding="utf-8")
            result = MANIFEST.determine_png_status(root)
            self.assertEqual(result["pngStatus"], "not-exported")
            self.assertEqual(result["pngStatusReason"], "custom reason")

    def test_not_exported_reports_pending_capture_contract_count(self):
        # export-grafana-evidence.py writes panel-<id>.capture.json for every
        # panel before any PNG exists (D-003-R1's capture contract). While no
        # PNGs are saved yet, that count should be visible in the manifest.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            (panels_dir / "panel-2.capture.json").write_text("{}", encoding="utf-8")
            (panels_dir / "panel-7.capture.json").write_text("{}", encoding="utf-8")
            result = MANIFEST.determine_png_status(root)
            self.assertEqual(result["pngStatus"], "not-exported")
            self.assertEqual(result["pendingCaptureContracts"], 2)

    def test_exported_when_every_png_has_a_matching_capture_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            for panel_id in (2, 3):
                (panels_dir / f"panel-{panel_id}.png").write_bytes(b"\x89PNG")
                (panels_dir / f"panel-{panel_id}.capture.json").write_text("{}", encoding="utf-8")
            result = MANIFEST.determine_png_status(root)
            self.assertEqual(result, {"pngStatus": "exported", "pngCount": 2, "linkedPngCount": 2})

    def test_flags_pngs_with_no_matching_capture_contract(self):
        # D-003-R1 / TEAM_MEMBER_B01_ACTION_REQUEST.md 4.4: a PNG must be
        # linked to runId/fromUtc/toUtc/dashboardUid+version/Query JSON. A
        # PNG dropped in without its capture.json sibling fails that link and
        # must not be silently counted as valid evidence.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            (panels_dir / "panel-2.png").write_bytes(b"\x89PNG")
            (panels_dir / "panel-2.capture.json").write_text("{}", encoding="utf-8")
            (panels_dir / "panel-9.png").write_bytes(b"\x89PNG")  # no matching capture.json

            result = MANIFEST.determine_png_status(root)

            self.assertEqual(result["pngStatus"], "exported-with-unlinked-files")
            self.assertEqual(result["pngCount"], 2)
            self.assertEqual(result["linkedPngCount"], 1)
            self.assertEqual(result["unlinkedPanelIds"], ["9"])
            self.assertIn("capture.json", result["pngStatusReason"])

    def test_flags_capture_contracts_with_no_matching_png(self):
        # A partial PNG set used to pass because the old check only computed
        # png_panel_ids - contract_panel_ids. The inverse must be checked too.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            (panels_dir / "panel-2.png").write_bytes(b"\x89PNG")
            for panel_id in (2, 7):
                (panels_dir / f"panel-{panel_id}.capture.json").write_text("{}", encoding="utf-8")

            result = MANIFEST.determine_png_status(root)

            self.assertEqual(result["pngStatus"], "exported-with-missing-files")
            self.assertEqual(result["missingPanelIds"], ["7"])
            self.assertEqual(result["linkedPngCount"], 1)

    def test_ignores_directories_named_like_png_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            (panels_dir / "panel-2.capture.json").write_text("{}", encoding="utf-8")
            (panels_dir / "panel-2.png").mkdir()

            result = MANIFEST.determine_png_status(root)

            self.assertEqual(result["pngStatus"], "not-exported")
            self.assertEqual(result["pendingCaptureContracts"], 1)


class DetermineDashboardStatusTest(unittest.TestCase):
    def test_dashboard_contract_without_png_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grafana = root / "grafana"
            grafana.mkdir()
            (grafana / "dashboard.capture.json").write_text(
                json.dumps({"expectedPngPath": "grafana/dashboard.png"}), encoding="utf-8"
            )
            result = MANIFEST.determine_dashboard_status(root)
            self.assertEqual(result["dashboardPngStatus"], "exported-with-missing-file")

    def test_dashboard_contract_and_png_are_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grafana = root / "grafana"
            grafana.mkdir()
            (grafana / "dashboard.capture.json").write_text(
                json.dumps({"expectedPngPath": "grafana/dashboard.png"}), encoding="utf-8"
            )
            (grafana / "dashboard.png").write_bytes(b"png-bytes")
            result = MANIFEST.determine_dashboard_status(root)
            self.assertEqual(result["dashboardPngStatus"], "exported")
            self.assertEqual(result["dashboardPngBytes"], len(b"png-bytes"))
            self.assertEqual(len(result["dashboardPngSha256"]), 64)


class DetermineQueryStatusTest(unittest.TestCase):
    def _write_contract(self, root: Path, panel_id: int = 2, query_paths=None):
        panels_dir = root / "grafana" / "panels"
        panels_dir.mkdir(parents=True, exist_ok=True)
        contract = {"panelId": panel_id, "queryJsonPaths": query_paths or [f"grafana/queries/panel-{panel_id}-A.json"]}
        (panels_dir / f"panel-{panel_id}.capture.json").write_text(json.dumps(contract), encoding="utf-8")

    def test_collected_when_every_contract_query_exists_and_is_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_contract(root)
            query_path = root / "grafana" / "queries" / "panel-2-A.json"
            query_path.parent.mkdir(parents=True)
            query_path.write_text(json.dumps({"status": "collected", "result": {}}), encoding="utf-8")

            result = MANIFEST.determine_query_status(root)

            self.assertEqual(result, {"queryStatus": "collected", "queryCount": 1})

    def test_incomplete_when_contract_query_is_missing_or_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_contract(root, panel_id=2)
            self._write_contract(root, panel_id=7)
            failed = root / "grafana" / "queries" / "panel-7-A.json"
            failed.parent.mkdir(parents=True, exist_ok=True)
            failed.write_text(json.dumps({"status": "error", "detail": "upstream unavailable"}), encoding="utf-8")

            result = MANIFEST.determine_query_status(root)

            self.assertEqual(result["queryStatus"], "incomplete")
            self.assertEqual(result["missingQueryJsonPaths"], ["grafana/queries/panel-2-A.json"])
            self.assertEqual(result["uncollectedQueryJsonPaths"], ["grafana/queries/panel-7-A.json"])

    def test_rejects_query_path_that_escapes_the_evidence_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_contract(root, query_paths=["../outside.json"])

            result = MANIFEST.determine_query_status(root)

            self.assertEqual(result["queryStatus"], "incomplete")
            self.assertEqual(result["missingQueryJsonPaths"], ["../outside.json"])


class BuildManifestTest(unittest.TestCase):
    def test_contains_sha256_bytes_and_source_for_every_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "k6").mkdir()
            (root / "k6" / "summary.json").write_text("{}", encoding="utf-8")
            (root / "grafana" / "queries").mkdir(parents=True)
            (root / "grafana" / "dashboard.json").write_text("{}", encoding="utf-8")
            (root / "grafana" / "queries" / "panel-2-A.json").write_text("{}", encoding="utf-8")
            (root / "metadata.json").write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")

            manifest = MANIFEST.build_manifest(root, "aws-b01-20260809-001")

            self.assertEqual(manifest["runId"], "aws-b01-20260809-001")
            self.assertEqual(manifest["fileCount"], 4)
            by_path = {entry["path"]: entry for entry in manifest["files"]}
            self.assertEqual(by_path["metadata.json"]["source"], "s3-download")
            self.assertEqual(by_path["k6/summary.json"]["source"], "s3-download")
            self.assertEqual(by_path["grafana/dashboard.json"]["source"], "grafana-export")
            self.assertEqual(by_path["grafana/queries/panel-2-A.json"]["source"], "grafana-export")
            for entry in manifest["files"]:
                self.assertEqual(len(entry["sha256"]), 64)
                self.assertGreaterEqual(entry["bytes"], 0)
            self.assertEqual(manifest["pngStatus"], "not-exported")


class CompareWithS3Test(unittest.TestCase):
    def test_all_match_when_checksums_agree(self):
        sha256_hex = hashlib.sha256(b"{}").hexdigest()
        expected_b64 = MANIFEST.hex_to_base64(sha256_hex)
        files = [{"path": "metadata.json", "sha256": sha256_hex}]

        original = MANIFEST.get_s3_checksum_base64
        MANIFEST.get_s3_checksum_base64 = lambda bucket, key, region: expected_b64
        try:
            result = MANIFEST.compare_with_s3("run-1", "bucket", "evidence/aws-load-tests", "ap-northeast-2", files)
        finally:
            MANIFEST.get_s3_checksum_base64 = original

        self.assertTrue(result["allMatch"])
        self.assertEqual(result["files"], [{"path": "metadata.json", "matches": True}])

    def test_flags_mismatch_without_raising(self):
        sha256_hex = hashlib.sha256(b"{}").hexdigest()
        files = [{"path": "metadata.json", "sha256": sha256_hex}]

        original = MANIFEST.get_s3_checksum_base64
        MANIFEST.get_s3_checksum_base64 = lambda bucket, key, region: "not-the-real-checksum"
        try:
            result = MANIFEST.compare_with_s3("run-1", "bucket", "evidence/aws-load-tests", "ap-northeast-2", files)
        finally:
            MANIFEST.get_s3_checksum_base64 = original

        self.assertFalse(result["allMatch"])
        self.assertFalse(result["files"][0]["matches"])

    def test_a_lookup_error_counts_as_mismatch_not_a_crash(self):
        files = [{"path": "metadata.json", "sha256": hashlib.sha256(b"{}").hexdigest()}]

        def raising_lookup(bucket, key, region):
            raise MANIFEST.ManifestError("simulated S3 error")

        original = MANIFEST.get_s3_checksum_base64
        MANIFEST.get_s3_checksum_base64 = raising_lookup
        try:
            result = MANIFEST.compare_with_s3("run-1", "bucket", "evidence/aws-load-tests", "ap-northeast-2", files)
        finally:
            MANIFEST.get_s3_checksum_base64 = original

        self.assertFalse(result["allMatch"])
        self.assertIn("detail", result["files"][0])


class MainIntegrationTest(unittest.TestCase):
    def test_main_writes_manifest_and_returns_zero_when_safe_and_no_s3_compare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")
            data_file = root / "data.json"
            data_file.write_text('{"credentials": []}', encoding="utf-8")

            import sys
            original_argv = sys.argv
            sys.argv = [
                "build-evidence-manifest.py",
                "--evidence-root", str(root),
                "--run-id", "aws-b01-20260809-001",
                "--data-file", str(data_file),
            ]
            try:
                exit_code = MANIFEST.main()
            finally:
                sys.argv = original_argv

            self.assertEqual(exit_code, 0)
            manifest_path = root / "manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["runId"], "aws-b01-20260809-001")
            self.assertTrue((root / "evidence-safety.json").exists())

    def test_main_raises_when_safety_scan_finds_a_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_file = root / "data.json"
            data_file.write_text(json.dumps({"credentials": [{"userId": "user-0000001", "refreshToken": "a-very-long-refresh-token-value"}]}), encoding="utf-8")
            (root / "leak.json").write_text('{"leaked": "a-very-long-refresh-token-value"}', encoding="utf-8")

            import sys
            original_argv = sys.argv
            sys.argv = [
                "build-evidence-manifest.py",
                "--evidence-root", str(root),
                "--run-id", "aws-b01-20260809-001",
                "--data-file", str(data_file),
            ]
            try:
                with self.assertRaises(MANIFEST.ManifestError):
                    MANIFEST.main()
            finally:
                sys.argv = original_argv

    def test_main_allows_post_retirement_local_scan_without_data_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text('{"runId": "aws-b01-20260809-001"}', encoding="utf-8")

            import sys
            original_argv = sys.argv
            sys.argv = [
                "build-evidence-manifest.py",
                "--evidence-root", str(root),
                "--run-id", "aws-b01-20260809-001",
            ]
            try:
                exit_code = MANIFEST.main()
            finally:
                sys.argv = original_argv

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "manifest.json").exists())

    def test_require_png_rejects_an_incomplete_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import sys
            original_argv = sys.argv
            sys.argv = [
                "build-evidence-manifest.py",
                "--evidence-root", str(root),
                "--run-id", "aws-b01-20260809-001",
                "--require-png",
            ]
            try:
                with self.assertRaises(MANIFEST.ManifestError):
                    MANIFEST.main()
            finally:
                sys.argv = original_argv

    def test_require_png_rejects_a_partial_png_set_even_when_one_png_is_linked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            queries_dir = root / "grafana" / "queries"
            queries_dir.mkdir(parents=True)
            for panel_id in (2, 7):
                (panels_dir / f"panel-{panel_id}.capture.json").write_text(
                    json.dumps({"panelId": panel_id, "queryJsonPaths": [f"grafana/queries/panel-{panel_id}-A.json"]}),
                    encoding="utf-8",
                )
                (queries_dir / f"panel-{panel_id}-A.json").write_text(
                    json.dumps({"status": "collected", "result": {}}), encoding="utf-8",
                )
            (panels_dir / "panel-2.png").write_bytes(b"\x89PNG")

            import sys
            original_argv = sys.argv
            sys.argv = [
                "build-evidence-manifest.py",
                "--evidence-root", str(root),
                "--run-id", "aws-b01-20260809-001",
                "--require-png",
            ]
            try:
                with self.assertRaises(MANIFEST.ManifestError):
                    MANIFEST.main()
            finally:
                sys.argv = original_argv

    def test_require_png_rejects_a_directory_named_like_a_png_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            queries_dir = root / "grafana" / "queries"
            queries_dir.mkdir(parents=True)
            (panels_dir / "panel-2.capture.json").write_text(
                json.dumps({"panelId": 2, "queryJsonPaths": ["grafana/queries/panel-2-A.json"]}), encoding="utf-8",
            )
            (queries_dir / "panel-2-A.json").write_text(
                json.dumps({"status": "collected", "result": {}}), encoding="utf-8",
            )
            (panels_dir / "panel-2.png").mkdir()

            import sys
            original_argv = sys.argv
            sys.argv = [
                "build-evidence-manifest.py",
                "--evidence-root", str(root),
                "--run-id", "aws-b01-20260809-001",
                "--require-png",
            ]
            try:
                with self.assertRaises(MANIFEST.ManifestError):
                    MANIFEST.main()
            finally:
                sys.argv = original_argv

    def test_require_png_accepts_complete_png_and_collected_query_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panels_dir = root / "grafana" / "panels"
            panels_dir.mkdir(parents=True)
            queries_dir = root / "grafana" / "queries"
            queries_dir.mkdir(parents=True)
            (panels_dir / "panel-2.capture.json").write_text(
                json.dumps({"panelId": 2, "queryJsonPaths": ["grafana/queries/panel-2-A.json"]}), encoding="utf-8",
            )
            (panels_dir / "panel-2.png").write_bytes(b"\x89PNG")
            (queries_dir / "panel-2-A.json").write_text(
                json.dumps({"status": "collected", "result": {}}), encoding="utf-8",
            )

            import sys
            original_argv = sys.argv
            sys.argv = [
                "build-evidence-manifest.py",
                "--evidence-root", str(root),
                "--run-id", "aws-b01-20260809-001",
                "--require-png",
            ]
            try:
                self.assertEqual(MANIFEST.main(), 0)
            finally:
                sys.argv = original_argv
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["pngStatus"], "exported")
            self.assertEqual(manifest["queryStatus"], "collected")


if __name__ == "__main__":
    unittest.main()
