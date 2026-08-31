"""Static contract tests for the disposable dev-eks load-test dashboard."""

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = REPO_ROOT / "monitoring" / "grafana" / "dashboards" / "aws-eks-load-test.json"


class EksLoadDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

    def test_json_and_identity_are_stable(self):
        self.assertEqual(self.dashboard["uid"], "aws-eks-load-test")
        self.assertEqual(self.dashboard["title"], "AWS EKS Load Test")
        self.assertEqual(self.dashboard["schemaVersion"], 41)

    def test_panel_ids_and_datasources_are_bounded(self):
        panels = self.dashboard["panels"]
        self.assertEqual(len({panel["id"] for panel in panels}), len(panels))
        self.assertTrue(all(panel["datasource"]["uid"] == "prometheus" for panel in panels))

    def test_queries_use_kubernetes_metrics_and_safe_labels(self):
        serialized = json.dumps(self.dashboard)
        self.assertIn("kube_pod_status_phase", serialized)
        self.assertIn("kube_deployment_status_replicas_available", serialized)
        self.assertIn("environment", serialized)
        for forbidden in ("userId", "user_id", "travelId", "travel_id", "requestId", "request_id", "flow_id"):
            self.assertNotIn(forbidden, serialized)

    def test_annotations_and_time_range_are_load_test_ready(self):
        annotations = json.dumps(self.dashboard["annotations"])
        self.assertIn("load-test", annotations)
        self.assertEqual(self.dashboard["time"], {"from": "now-1h", "to": "now"})


if __name__ == "__main__":
    unittest.main()
