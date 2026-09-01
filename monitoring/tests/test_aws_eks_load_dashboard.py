"""Static contract tests for the disposable dev-eks load-test dashboard."""

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = REPO_ROOT / "monitoring" / "grafana" / "dashboards" / "aws-eks-load-test.json"
QUERY_CONTRACT_PATH = REPO_ROOT / "monitoring" / "grafana" / "contracts" / "aws-eks-load-test-required-queries.json"


class EksLoadDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
        cls.query_contract = json.loads(QUERY_CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_json_and_identity_are_stable(self):
        self.assertEqual(self.dashboard["uid"], "aws-eks-load-test")
        self.assertEqual(self.dashboard["title"], "AWS EKS Load Test")
        self.assertEqual(self.dashboard["schemaVersion"], 41)

    def test_panel_ids_and_datasources_are_bounded(self):
        panels = self.dashboard["panels"]
        self.assertEqual(len({panel["id"] for panel in panels}), len(panels))
        self.assertTrue(all(panel["datasource"]["uid"] in {"prometheus", "cloudwatch"} for panel in panels))

    def test_queries_use_kubernetes_metrics_and_safe_labels(self):
        serialized = json.dumps(self.dashboard)
        self.assertIn("kube_pod_status_phase", serialized)
        self.assertIn("kube_deployment_status_replicas_available", serialized)
        self.assertIn("kube_horizontalpodautoscaler_status_desired_replicas", serialized)
        self.assertIn("kube_node_status_condition", serialized)
        self.assertIn("http_server_requests_seconds_bucket", serialized)
        self.assertIn("hikaricp_connections_pending", serialized)
        cpu_panel = next(panel for panel in self.dashboard["panels"] if panel["id"] == 9)
        self.assertEqual(
            cpu_panel["targets"][0]["expr"],
            '100 * avg(process_cpu_usage{app="travel-planner-backend",environment="$environment"})',
        )
        self.assertNotIn("process_cpu_seconds_total{app=", serialized)
        self.assertNotIn("node_cpu_seconds_total", serialized)
        self.assertIn("environment", serialized)
        for forbidden in ("userId", "user_id", "travelId", "travel_id", "requestId", "request_id", "flow_id"):
            self.assertNotIn(forbidden, serialized)

    def test_annotations_and_time_range_are_load_test_ready(self):
        annotations = json.dumps(self.dashboard["annotations"])
        self.assertIn("load-test", annotations)
        self.assertEqual(self.dashboard["time"], {"from": "now-1h", "to": "now"})

    def test_scale_slo_and_bottleneck_panels_are_separable(self):
        titles = {panel["title"] for panel in self.dashboard["panels"]}
        self.assertTrue({
            "Backend HPA desired / current / max",
            "Ready node count",
            "Scheduling pressure",
            "Backend throughput",
            "Backend latency p95",
            "Backend 5xx ratio",
            "Backend process CPU",
            "Backend JVM heap",
            "Backend Hikari connections",
        }.issubset(titles))

    def test_every_prometheus_target_has_required_query_policy(self):
        policy_keys = {item["key"] for item in self.query_contract["queries"]}
        actual_keys = {
            f"{panel['id']}/{target['refId']}"
            for panel in self.dashboard["panels"]
            for target in panel.get("targets", [])
        }
        self.assertEqual(actual_keys, policy_keys)
        self.assertEqual(self.query_contract["dashboardUid"], self.dashboard["uid"])
        self.assertEqual(
            set(self.query_contract["statuses"]),
            {"collected", "empty", "stale", "error"},
        )

    def test_dashboard_queries_have_no_unresolved_custom_variables_except_templates(self):
        for panel in self.dashboard["panels"]:
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                self.assertNotIn("$__all", expr)
                self.assertNotIn("$__interval", expr)
                self.assertTrue(
                    all(variable in {"namespace", "environment"} for variable in _custom_variables(expr)),
                    f"unexpected dashboard variable in panel {panel['id']}: {expr}",
                )


def _custom_variables(expr: str) -> set[str]:
    import re
    return set(re.findall(r"\$(?!__)([A-Za-z_][A-Za-z0-9_]*)", expr))


if __name__ == "__main__":
    unittest.main()
