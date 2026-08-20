from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
DASHBOARD = ROOT / "monitoring/grafana/dashboards/compose-sql-round-trip-diagnostic.json"
PROMETHEUS = ROOT / "monitoring/prometheus/prometheus.sql-diagnostic.yml"
OVERLAY = ROOT / "compose.monitoring.sql-diagnostic.yml"
INIT_SQL = ROOT / "load-tests/sql/enable-pg-stat-statements.sql"


class ComposeSqlRoundTripDashboardTest(unittest.TestCase):
    def test_dashboard_contract_and_bounded_labels(self) -> None:
        dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        self.assertEqual(dashboard["uid"], "compose-sql-round-trip-diagnostic")
        self.assertGreaterEqual(len(dashboard["panels"]), 14)
        expressions = "\n".join(
            target["expr"] for panel in dashboard["panels"] for target in panel.get("targets", [])
        )
        for metric in (
            "scrum41_sql_diagnostic_api_duration_ms",
            "scrum41_sql_diagnostic_sql_calls_per_request",
            "scrum41_sql_diagnostic_db_exec_ms_per_request",
            "scrum41_sql_diagnostic_db_mean_exec_ms_per_call",
            "scrum41_sql_diagnostic_update_amplification",
            "pg_locks_count",
            "hikaricp_connections_pending",
        ):
            self.assertIn(metric, expressions)
        serialized = json.dumps(dashboard).lower()
        for forbidden in ("request_id", "requestid", "item_id", "itemid", "password", "cookie", "jwt"):
            self.assertNotIn(forbidden, serialized)
        variables = {variable["name"] for variable in dashboard["templating"]["list"]}
        self.assertEqual(variables, {"replicate", "mode", "item_count", "query_family"})

    def test_prometheus_has_pushgateway_and_sql_exporter_targets(self) -> None:
        prometheus = PROMETHEUS.read_text(encoding="utf-8")
        self.assertIn("pushgateway:9091", prometheus)
        self.assertIn("postgres-exporter:9187", prometheus)
        self.assertIn("honor_labels: true", prometheus)
        self.assertIn("backend:9091", prometheus)

    def test_overlay_enables_preload_exporter_and_digest_without_host_pushgateway_port(self) -> None:
        overlay = OVERLAY.read_text(encoding="utf-8")
        self.assertIn("shared_preload_libraries=pg_stat_statements", overlay)
        self.assertIn("compute_query_id=on", overlay)
        self.assertIn("track_io_timing=on", overlay)
        self.assertIn("--collector.stat_statements", overlay)
        self.assertIn("prom/pushgateway:v1.11.1@sha256:", overlay)
        self.assertNotIn("ports:\n      - \"127.0.0.1", overlay)
        self.assertNotIn(":latest", overlay)
        self.assertNotIn("request_id", overlay)
        self.assertNotIn("item_id", overlay)

    def test_init_sql_is_idempotent_and_only_enables_extension(self) -> None:
        sql = INIT_SQL.read_text(encoding="utf-8").lower()
        self.assertIn("create extension if not exists pg_stat_statements", sql)
        self.assertNotIn("drop database", sql)
        self.assertNotIn("password", sql)


if __name__ == "__main__":
    unittest.main()
