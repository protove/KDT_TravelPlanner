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


EXPORT = _load("export_grafana_evidence", "scripts/loadtest/aws/export-grafana-evidence.py")


SAMPLE_DASHBOARD_PAYLOAD = {
    "dashboard": {
        "uid": "aws-load-test-b01",
        "panels": [
            {
                "id": 1,
                "title": "Run metadata",
                "datasource": {"type": "datasource", "uid": "-- Dashboard --"},
                "targets": [],
            },
            {
                "id": 2,
                "title": "k6 request duration p95/p99",
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "targets": [
                    {"refId": "A", "expr": "k6_http_req_duration_p95"},
                    {"refId": "B", "expr": "k6_http_req_duration_p99"},
                ],
            },
            {
                "id": 14,
                "title": "WARN/ERROR log rate",
                "datasource": {"type": "loki", "uid": "loki"},
                "targets": [{"refId": "A", "expr": "sum by (level) (count_over_time({service=\"x\"}[1m]))"}],
            },
            {
                "id": 7,
                "title": "ALB RequestCount",
                "datasource": {"type": "cloudwatch", "uid": "cloudwatch"},
                "targets": [{
                    "refId": "A", "namespace": "AWS/ApplicationELB", "metricName": "RequestCount",
                    "statistic": "Sum", "period": "60", "dimensions": {},
                }],
            },
        ],
    },
    "meta": {"version": 1},
}


class ResolveTimeRangeTest(unittest.TestCase):
    def test_explicit_flags_win_even_without_metadata_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = EXPORT.resolve_time_range(root, "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z")
            self.assertEqual(result, ("2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z"))

    def test_falls_back_to_metadata_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({
                "runId": "aws-b01-20260811-090000",
                "startedAtUtc": "2026-08-11T09:00:00Z",
                "endedAtUtc": "2026-08-11T10:00:00Z",
            }), encoding="utf-8")
            result = EXPORT.resolve_time_range(root, "", "")
            self.assertEqual(result, ("2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z"))

    def test_raises_when_metadata_json_missing_and_no_override(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.resolve_time_range(Path(directory), "", "")

    def test_raises_when_ended_at_utc_still_null(self):
        # target_stage writes endedAtUtc=null; orchestrate-aws-b01.sh's
        # cleanup_stage fills it in later. If cleanup hasn't run yet, this
        # must fail loudly rather than silently querying an open-ended range.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({
                "runId": "aws-b01-20260811-090000",
                "startedAtUtc": "2026-08-11T09:00:00Z",
                "endedAtUtc": None,
            }), encoding="utf-8")
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.resolve_time_range(root, "", "")


class ResolveRunIdTest(unittest.TestCase):
    def test_explicit_run_id_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(EXPORT.resolve_run_id(Path(directory), "explicit-id"), "explicit-id")

    def test_falls_back_to_metadata_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({"runId": "aws-b01-20260811-090000"}), encoding="utf-8")
            self.assertEqual(EXPORT.resolve_run_id(root, ""), "aws-b01-20260811-090000")

    def test_raises_when_neither_available(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.resolve_run_id(Path(directory), "")


class BasicAuthHeaderTest(unittest.TestCase):
    def test_header_decodes_back_to_user_and_password(self):
        import base64
        header = EXPORT.basic_auth_header("evidence-exporter", "s3cr3t")
        self.assertTrue(header.startswith("Basic "))
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode("ascii")
        self.assertEqual(decoded, "evidence-exporter:s3cr3t")


class ToEpochSecondsTest(unittest.TestCase):
    def test_known_timestamp(self):
        self.assertEqual(EXPORT.to_epoch_seconds("1970-01-01T00:00:00Z"), 0)

    def test_one_hour_later(self):
        self.assertEqual(EXPORT.to_epoch_seconds("1970-01-01T01:00:00Z"), 3600)


class ExtractPanelQueriesTest(unittest.TestCase):
    def test_skips_text_panel_with_no_real_datasource(self):
        queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        panel_ids = {entry["panelId"] for entry in queries}
        self.assertNotIn(1, panel_ids)

    def test_extracts_one_entry_per_prometheus_target(self):
        queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        prom_entries = [q for q in queries if q["panelId"] == 2]
        self.assertEqual(len(prom_entries), 2)
        ref_ids = {entry["refId"] for entry in prom_entries}
        self.assertEqual(ref_ids, {"A", "B"})
        for entry in prom_entries:
            self.assertEqual(entry["datasourceType"], "prometheus")
            self.assertIn("expr", entry)

    def test_extracts_loki_panel(self):
        queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        loki_entries = [q for q in queries if q["panelId"] == 14]
        self.assertEqual(len(loki_entries), 1)
        self.assertEqual(loki_entries[0]["datasourceType"], "loki")

    def test_extracts_cloudwatch_panel_with_nested_params(self):
        queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        cw_entries = [q for q in queries if q["panelId"] == 7]
        self.assertEqual(len(cw_entries), 1)
        self.assertEqual(cw_entries[0]["datasourceType"], "cloudwatch")
        self.assertEqual(cw_entries[0]["cloudwatch"]["namespace"], "AWS/ApplicationELB")
        self.assertEqual(cw_entries[0]["cloudwatch"]["metricName"], "RequestCount")

    def test_empty_panels_list_yields_no_queries(self):
        self.assertEqual(EXPORT.extract_panel_queries({"dashboard": {"panels": []}}), [])


class CollectPanelQueriesTest(unittest.TestCase):
    def test_writes_one_file_per_query_and_counts_success_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            queries_dir = Path(directory)
            panel_queries = [
                {"panelId": 2, "refId": "A", "datasourceType": "prometheus", "datasourceUid": "prometheus", "expr": "up"},
                {"panelId": 7, "refId": "A", "datasourceType": "cloudwatch", "datasourceUid": "cloudwatch",
                 "cloudwatch": {"namespace": "AWS/ApplicationELB", "metricName": "RequestCount", "statistic": "Sum", "period": "60", "dimensions": {}}},
            ]

            original_grafana_request = EXPORT.grafana_request
            original_run_command = EXPORT.run_command
            EXPORT.grafana_request = lambda url, auth_header, timeout=15: json.dumps({"status": "success", "data": {}}).encode("utf-8")
            EXPORT.run_command = lambda command: json.dumps({"Datapoints": []})
            try:
                collected, failed = EXPORT.collect_panel_queries(
                    "http://127.0.0.1:3000", "Basic xyz", panel_queries, "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z", "ap-northeast-2", queries_dir,
                )
            finally:
                EXPORT.grafana_request = original_grafana_request
                EXPORT.run_command = original_run_command

            self.assertEqual((collected, failed), (2, 0))
            written = sorted(p.name for p in queries_dir.glob("*.json"))
            self.assertEqual(written, ["panel-2-A.json", "panel-7-A.json"])
            for name in written:
                record = json.loads((queries_dir / name).read_text(encoding="utf-8"))
                self.assertEqual(record["status"], "collected")
                self.assertEqual(record["fromUtc"], "2026-08-11T09:00:00Z")

    def test_a_failing_query_does_not_abort_the_others(self):
        with tempfile.TemporaryDirectory() as directory:
            queries_dir = Path(directory)
            panel_queries = [
                {"panelId": 2, "refId": "A", "datasourceType": "prometheus", "datasourceUid": "prometheus", "expr": "up"},
                {"panelId": 3, "refId": "A", "datasourceType": "prometheus", "datasourceUid": "prometheus", "expr": "down"},
            ]
            calls = {"n": 0}

            def flaky_grafana_request(url, auth_header, timeout=15):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise EXPORT.ExportError("simulated network failure")
                return json.dumps({"status": "success"}).encode("utf-8")

            original_grafana_request = EXPORT.grafana_request
            EXPORT.grafana_request = flaky_grafana_request
            try:
                collected, failed = EXPORT.collect_panel_queries(
                    "http://127.0.0.1:3000", "Basic xyz", panel_queries, "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z", "", queries_dir,
                )
            finally:
                EXPORT.grafana_request = original_grafana_request

            self.assertEqual((collected, failed), (1, 1))
            self.assertEqual(len(list(queries_dir.glob("*.json"))), 2)

    def test_missing_region_fails_cloudwatch_query_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            queries_dir = Path(directory)
            panel_queries = [{
                "panelId": 7, "refId": "A", "datasourceType": "cloudwatch", "datasourceUid": "cloudwatch",
                "cloudwatch": {"namespace": "AWS/ApplicationELB", "metricName": "RequestCount", "statistic": "Sum", "period": "60", "dimensions": {}},
            }]
            collected, failed = EXPORT.collect_panel_queries(
                "http://127.0.0.1:3000", "Basic xyz", panel_queries, "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z", "", queries_dir,
            )
            self.assertEqual((collected, failed), (0, 1))
            record = json.loads((queries_dir / "panel-7-A.json").read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "error")


if __name__ == "__main__":
    unittest.main()
