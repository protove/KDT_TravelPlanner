from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUMMARY = load_module("scrum41_sql_summary", ROOT / "scripts/loadtest/summarize-compose-sql-round-trip-diagnostic.py")
RUNNER = load_module("scrum41_sql_runner", ROOT / "scripts/loadtest/run-compose-sql-round-trip-diagnostic.py")
SAFETY = load_module("scrum41_sql_safety", ROOT / "scripts/loadtest/verify-compose-sql-diagnostic-evidence.py")
CAPTURE = load_module("scrum41_sql_capture", ROOT / "scripts/loadtest/verify-compose-sql-grafana-captures.py")


class SqlDiagnosticSummaryTest(unittest.TestCase):
    def test_k6_metric_values_support_native_and_fixture_shapes(self) -> None:
        self.assertEqual(SUMMARY.metric_values({"http_req_duration": {"p(95)": 12.5}}, "http_req_duration"), {"p(95)": 12.5})
        self.assertEqual(SUMMARY.metric_values({"http_req_duration": {"values": {"p(95)": 12.5}}}, "http_req_duration"), {"p(95)": 12.5})

    def test_classifier_excludes_postgres_observability_queries_from_unknown_application_sql(self) -> None:
        system_queries = (
            "SELECT * FROM pg_stat_database",
            "SELECT name, setting FROM pg_settings",
            "SELECT clock_timestamp()::text",
            "SELECT version()",
        )
        for query in system_queries:
            normalized = RUNNER.normalize_query(query)
            self.assertEqual(RUNNER.classify_query(normalized), "transaction_or_session", query)
        self.assertEqual(RUNNER.classify_query("SELECT * FROM MYSTERY_TABLE"), "unknown_application_table_statement")

    def test_classification_branches_are_fixed_and_replicate_gated(self) -> None:
        base = {"replicate": 1, "valid": True}

        def feature(**changes):
            value = {
                "replicate": 1,
                "confirmedRepeatedSqlRoundTrips": False,
                "reverseSqlCallsRatio200To3": 1.0,
                "reverseApiP95Ratio200To3": 1.0,
                "reverseDbExecRatio200To3": 1.0,
                "reverseMeanCallRatio200To3": 1.0,
                "noopApiP95Ratio200To3": 1.0,
                "reverseToNoopApiP95RatioAt200": 1.0,
                "timelineUpdateMeanExecMsMax": 1.0,
            }
            value.update(changes)
            return value

        stages = [dict(base, replicate=1), dict(base, replicate=2)]
        confirmed = SUMMARY.classify(stages, [feature(confirmedRepeatedSqlRoundTrips=True), feature(replicate=2, confirmedRepeatedSqlRoundTrips=True)], 2)
        self.assertEqual(confirmed["verdict"], "confirmed-repeated-sql-round-trips")

        slow = SUMMARY.classify(stages, [feature(reverseSqlCallsRatio200To3=1.5, reverseApiP95Ratio200To3=2.2, reverseDbExecRatio200To3=2.3), feature(replicate=2, reverseSqlCallsRatio200To3=1.5, reverseApiP95Ratio200To3=2.2, reverseMeanCallRatio200To3=2.4)], 2)
        self.assertEqual(slow["verdict"], "probable-slow-individual-sql")

        payload = SUMMARY.classify(stages, [feature(noopApiP95Ratio200To3=2.2), feature(replicate=2, noopApiP95Ratio200To3=2.3)], 2)
        self.assertEqual(payload["verdict"], "probable-application-or-payload")

        mixed = SUMMARY.classify(stages, [feature(reverseSqlCallsRatio200To3=4.0, timelineUpdateMeanExecMsMax=6.0), feature(replicate=2, reverseSqlCallsRatio200To3=4.0, timelineUpdateMeanExecMsMax=6.0)], 2)
        self.assertEqual(mixed["verdict"], "mixed-db-amplification")

        inconclusive = SUMMARY.classify([dict(base, valid=False)], [feature()], 2)
        self.assertEqual(inconclusive["verdict"], "inconclusive")

    def test_summarize_replays_minimal_valid_stage_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "campaign-metadata.json").write_text(json.dumps({"campaignId": "fixture", "replicates": 1}), encoding="utf-8")
            for mode in ("noop", "reverse"):
                for count in (3, 10, 25, 50, 100, 200):
                    stage = root / "replicate-1" / "stages" / f"{mode}-{count}"
                    stage.mkdir(parents=True)
                    (stage / "metadata.json").write_text(json.dumps({"replicate": 1, "mode": mode, "itemCount": count, "measuredIterations": 4, "canonicalAfterMeasured": True}), encoding="utf-8")
                    (stage / "run-status.json").write_text(json.dumps({"k6ExitCode": 0}), encoding="utf-8")
                    (stage / "k6-native-summary.json").write_text(json.dumps({"metrics": {"http_req_duration": {"values": {"p(95)": count + (100 if mode == "reverse" else 1), "avg": count}}, "http_reqs": {"values": {"count": 4}}, "sql_diagnostic_successful_requests": {"values": {"count": 4}}, "sql_diagnostic_contract_failures": {"values": {"rate": 0}}, "dropped_iterations": {"values": {"count": 0}}}}), encoding="utf-8")
                    (stage / "pg-stat-statements.json").write_text(json.dumps({"resetAtUtc": "2026-01-01T00:00:00Z", "snapshotAtUtc": "2026-01-01T00:00:01Z", "unknownCount": 0, "statements": [{"queryFamily": "timeline_update", "normalizedQuery": "UPDATE TIMELINE_TABLE SET VISIT_ORDER = ?", "calls": 3 * (count // 2) if mode == "reverse" else 0, "rows": 1, "totalExecMs": 1, "meanExecMs": 0.1}], "queryFamilies": {"timeline_update": {"calls": 3 * (count // 2) if mode == "reverse" else 0, "totalExecMs": 1, "meanExecMs": 0.1}}}), encoding="utf-8")
                    (stage / "backend-metric-delta.json").write_text(json.dumps({"after": {"pg_stat_database_deadlocks": 0}}), encoding="utf-8")
            (root / "replicate-1" / "service-stats.jsonl").write_text("", encoding="utf-8")
            summary, verdict = SUMMARY.summarize(root, required_replicates=1)
            self.assertEqual(len(summary["stages"]), 12)
            self.assertEqual(summary["validity"]["validStageCount"], 12)
            self.assertIn(verdict["verdict"], {"confirmed-repeated-sql-round-trips", "inconclusive"})
            self.assertTrue((root / "SQL_DIAGNOSTIC_REPORT.md").is_file())

    def test_safety_rejects_uuid_in_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "campaign-metadata.json").write_text("{}", encoding="utf-8")
            (root / "campaign-manifest.json").write_text(json.dumps({"sourceDigests": {"profile": "x"}}), encoding="utf-8")
            replicate = root / "replicate-1"
            (replicate / "stages" / "noop-3").mkdir(parents=True)
            for name in ("replicate-metadata.json", "fixture-manifest.json", "metric-inventory.json"):
                (replicate / name).write_text("{}", encoding="utf-8")
            (replicate / "service-stats.jsonl").write_text("", encoding="utf-8")
            for name in ("metadata.json", "operations.jsonl", "raw.json", "k6-native-summary.json", "run-status.json", "pg-stat-statements.json", "query-breakdown.json", "backend-metric-delta.json"):
                (replicate / "stages" / "noop-3" / name).write_text('{"safe": "00000000-0000-4000-8000-000000000000"}' if name == "raw.json" else "{}", encoding="utf-8")
            with self.assertRaises(SAFETY.EvidenceError):
                SAFETY.verify(root)

    def test_capture_verifier_fails_closed_without_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grafana = root / "grafana"
            grafana.mkdir(parents=True)
            (grafana / "capture-metadata.json").write_text(json.dumps({"dashboardUid": "compose-sql-round-trip-diagnostic", "fromUtc": "2026-01-01T00:00:00Z", "toUtc": "2026-01-01T00:00:01Z"}), encoding="utf-8")
            with self.assertRaises(CAPTURE.CaptureError):
                CAPTURE.verify(root)


if __name__ == "__main__":
    unittest.main()
