from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
DASHBOARD = ROOT / "monitoring/grafana/dashboards/compose-dependency-diagnostic.json"
PROMETHEUS = ROOT / "monitoring/prometheus/prometheus.diagnostic.yml"
OVERLAY = ROOT / "compose.monitoring.diagnostic.yml"


class ComposeDependencyDashboardTest(unittest.TestCase):
    def test_dashboard_uid_and_required_dependency_panels(self) -> None:
        dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        self.assertEqual(dashboard["uid"], "compose-dependency-diagnostic")
        self.assertGreaterEqual(len(dashboard["panels"]), 12)
        expressions = "\n".join(target["expr"] for panel in dashboard["panels"] for target in panel.get("targets", []))
        for metric in ("hikaricp_connections_pending", "pg_stat_database_xact_commit", "redis_memory_used_bytes", "k6_diagnostic_reorder_item_count"):
            self.assertIn(metric, expressions)
        variables = dashboard["templating"]["list"]
        self.assertTrue(all("k6_http_req_duration_p95" in variable["query"] for variable in variables))
        self.assertNotIn("password", DASHBOARD.read_text(encoding="utf-8").lower())

    def test_prometheus_scrapes_both_exporters_and_overlay_uses_digest(self) -> None:
        prometheus = PROMETHEUS.read_text(encoding="utf-8")
        overlay = OVERLAY.read_text(encoding="utf-8")
        self.assertIn("postgres-exporter:9187", prometheus)
        self.assertIn("redis-exporter:9121", prometheus)
        self.assertIn("--web.enable-remote-write-receiver", overlay)
        self.assertIn("@sha256:", overlay)
        self.assertNotIn(":latest", overlay)


if __name__ == "__main__":
    unittest.main()
