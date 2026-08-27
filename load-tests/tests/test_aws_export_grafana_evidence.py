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


class ResourceDimensionsValidationTest(unittest.TestCase):
    COMPLETE = {
        "albDimension": "app/kdt-travelplanner-dev-api/51b33ebe03b9146c",
        "targetGroupDimension": "targetgroup/kdt-travelplanner-dev-backend/bb07fdde9f6dfbdc",
        "autoScalingGroupName": "kdt-travelplanner-dev-backend",
        "dbInstanceIdentifier": "kdt-travelplanner-dev-postgres",
        "cacheClusterId": "kdt-travelplanner-dev-redis-001",
    }

    def test_accepts_all_runtime_dimensions(self):
        EXPORT.validate_resource_dimensions(self.COMPLETE)

    def test_rejects_missing_runtime_dimension(self):
        incomplete = dict(self.COMPLETE)
        incomplete["cacheClusterId"] = None
        with self.assertRaises(EXPORT.ExportError):
            EXPORT.validate_resource_dimensions(incomplete)

    def test_rejects_dashboard_placeholder_dimension(self):
        placeholder = dict(self.COMPLETE)
        placeholder["albDimension"] = "__runtime__"
        with self.assertRaises(EXPORT.ExportError):
            EXPORT.validate_resource_dimensions(placeholder)


class BasicAuthHeaderTest(unittest.TestCase):
    def test_header_decodes_back_to_user_and_password(self):
        import base64
        header = EXPORT.basic_auth_header("evidence-exporter", "s3cr3t")
        self.assertTrue(header.startswith("Basic "))
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode("ascii")
        self.assertEqual(decoded, "evidence-exporter:s3cr3t")


class GrafanaCaptureContractTest(unittest.TestCase):
    def test_loopback_endpoint_is_required_for_capture(self):
        self.assertTrue(EXPORT.is_loopback_grafana_url("http://127.0.0.1:3000"))
        self.assertTrue(EXPORT.is_loopback_grafana_url("http://localhost:3000"))
        self.assertFalse(EXPORT.is_loopback_grafana_url("https://grafana.example.com"))

    def test_full_dashboard_contract_contains_fixed_window_and_png_path(self):
        contract = EXPORT.build_dashboard_capture_contract(
            SAMPLE_DASHBOARD_PAYLOAD,
            "http://127.0.0.1:3000",
            "scrum43-r01-ec2-capture",
            "2026-08-11T09:00:00Z",
            "2026-08-11T10:00:00Z",
        )
        self.assertEqual(contract["expectedPngPath"], "grafana/dashboard.png")
        self.assertIn("from=1786438800000", contract["captureUrl"])
        self.assertIn("to=1786442400000", contract["captureUrl"])
        self.assertIn("tz=utc", contract["captureUrl"])


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

    def test_cloudwatch_dimension_variables_resolve_from_target_contract(self):
        payload = json.loads(json.dumps(SAMPLE_DASHBOARD_PAYLOAD))
        payload["dashboard"]["panels"][-1]["targets"][0]["dimensions"] = {"LoadBalancer": "$alb_dimension"}
        queries = EXPORT.extract_panel_queries(payload, {"albDimension": "app/example/abc"})
        cloudwatch = next(q for q in queries if q["panelId"] == 7)
        self.assertEqual(cloudwatch["cloudwatch"]["dimensions"], {"LoadBalancer": "app/example/abc"})

    def test_cloudwatch_empty_dimensions_are_rejected_for_live_export(self):
        with self.assertRaises(EXPORT.ExportError):
            EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD, {})


class CollectPanelQueriesTest(unittest.TestCase):
    def test_cloudwatch_command_keeps_all_dimensions_in_one_cli_list(self):
        captured = []
        original_run_command = EXPORT.run_command
        EXPORT.run_command = lambda command: captured.append(command) or json.dumps({"Datapoints": []})
        try:
            EXPORT.collect_cloudwatch_query(
                "AWS/ApplicationELB",
                "HealthyHostCount",
                "Minimum",
                "60",
                {
                    "LoadBalancer": "app/example/abc",
                    "TargetGroup": "targetgroup/example/def",
                },
                "ap-northeast-2",
                "2026-08-11T09:00:00Z",
                "2026-08-11T10:00:00Z",
            )
        finally:
            EXPORT.run_command = original_run_command

        command = captured[0]
        dimensions_index = command.index("--dimensions")
        self.assertEqual(command.count("--dimensions"), 1)
        self.assertEqual(
            command[dimensions_index + 1:dimensions_index + 3],
            [
                "Name=LoadBalancer,Value=app/example/abc",
                "Name=TargetGroup,Value=targetgroup/example/def",
            ],
        )

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


class BuildPanelCaptureContractsTest(unittest.TestCase):
    def test_one_contract_per_panel_not_per_target(self):
        panel_queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        contracts = EXPORT.build_panel_capture_contracts(
            SAMPLE_DASHBOARD_PAYLOAD, panel_queries, "http://127.0.0.1:3000", "aws-b01-20260811-090000",
            "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z",
        )
        panel_ids = [c["panelId"] for c in contracts]
        self.assertEqual(panel_ids, [2, 7, 14])  # panel 2 has two targets (A, B) but one contract

    def test_multi_target_panel_lists_every_query_json_path(self):
        panel_queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        contracts = EXPORT.build_panel_capture_contracts(
            SAMPLE_DASHBOARD_PAYLOAD, panel_queries, "http://127.0.0.1:3000", "aws-b01-20260811-090000",
            "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z",
        )
        panel_2 = next(c for c in contracts if c["panelId"] == 2)
        self.assertEqual(
            sorted(panel_2["queryJsonPaths"]),
            ["grafana/queries/panel-2-A.json", "grafana/queries/panel-2-B.json"],
        )

    def test_runtime_dimensions_are_injected_into_dashboard_and_capture_urls(self):
        contracts = EXPORT.build_panel_capture_contracts(
            SAMPLE_DASHBOARD_PAYLOAD,
            EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD),
            "http://127.0.0.1:3000",
            "aws-b01-20260811-090000",
            "2026-08-11T09:00:00Z",
            "2026-08-11T10:00:00Z",
            ResourceDimensionsValidationTest.COMPLETE,
        )
        contract = next(item for item in contracts if item["panelId"] == 7)
        self.assertIn(
            "var-alb_dimension=app%2Fkdt-travelplanner-dev-api%2F51b33ebe03b9146c",
            contract["dashboardUrl"],
        )
        self.assertIn(
            "var-cache_cluster_id=kdt-travelplanner-dev-redis-001",
            contract["dashboardUrl"],
        )
        self.assertIn("viewPanel=7", contract["captureUrl"])

    def test_contract_carries_run_id_and_fixed_utc_range(self):
        panel_queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        contracts = EXPORT.build_panel_capture_contracts(
            SAMPLE_DASHBOARD_PAYLOAD, panel_queries, "http://127.0.0.1:3000", "aws-b01-20260811-090000",
            "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z",
        )
        for contract in contracts:
            self.assertEqual(contract["runId"], "aws-b01-20260811-090000")
            self.assertEqual(contract["fromUtc"], "2026-08-11T09:00:00Z")
            self.assertEqual(contract["toUtc"], "2026-08-11T10:00:00Z")
            self.assertEqual(contract["dashboardUid"], "aws-load-test-b01")
            self.assertEqual(contract["expectedPngPath"], f"grafana/panels/panel-{contract['panelId']}.png")

    def test_capture_url_encodes_panel_id_and_fixed_epoch_ms_range(self):
        panel_queries = EXPORT.extract_panel_queries(SAMPLE_DASHBOARD_PAYLOAD)
        contracts = EXPORT.build_panel_capture_contracts(
            SAMPLE_DASHBOARD_PAYLOAD, panel_queries, "http://127.0.0.1:3000", "aws-b01-20260811-090000",
            "1970-01-01T00:00:00Z", "1970-01-01T01:00:00Z",
        )
        panel_7 = next(c for c in contracts if c["panelId"] == 7)
        self.assertEqual(
            panel_7["captureUrl"],
            "http://127.0.0.1:3000/d/aws-load-test-b01?viewPanel=7&from=0&to=3600000&tz=utc",
        )

    def test_empty_panel_queries_yields_no_contracts(self):
        self.assertEqual(
            EXPORT.build_panel_capture_contracts(SAMPLE_DASHBOARD_PAYLOAD, [], "http://x", "run-1", "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z"),
            [],
        )


class WritePanelCaptureContractsTest(unittest.TestCase):
    def test_writes_one_file_per_contract_named_by_panel_id(self):
        with tempfile.TemporaryDirectory() as directory:
            panels_dir = Path(directory)
            contracts = [
                {"panelId": 2, "panelTitle": "k6 duration"},
                {"panelId": 7, "panelTitle": "ALB RequestCount"},
            ]
            EXPORT.write_panel_capture_contracts(contracts, panels_dir)
            written = sorted(p.name for p in panels_dir.glob("*.capture.json"))
            self.assertEqual(written, ["panel-2.capture.json", "panel-7.capture.json"])
            content = json.loads((panels_dir / "panel-2.capture.json").read_text(encoding="utf-8"))
            self.assertEqual(content["panelTitle"], "k6 duration")


if __name__ == "__main__":
    unittest.main()
