import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPOSITORY_ROOT / "monitoring/grafana/dashboards/aws-load-test.json"
EKS_DASHBOARD = REPOSITORY_ROOT / "monitoring/grafana/dashboards/aws-eks-load-test.json"
EKS_QUERY_CONTRACT = REPOSITORY_ROOT / "monitoring/grafana/contracts/aws-eks-load-test-required-queries.json"


class AwsDashboardContractTest(unittest.TestCase):
    def test_required_dashboard_excludes_optional_k6_remote_write_panels(self):
        payload = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        titles = {panel.get("title") for panel in payload.get("panels", [])}
        self.assertNotIn("k6 request duration p95/p99", titles)
        self.assertNotIn("k6 success RPS / errors / dropped iterations", titles)
        self.assertNotIn("Contract failures (this range)", titles)

    def test_cloudwatch_targets_are_scoped_to_named_resource_dimensions(self):
        payload = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        cloudwatch_targets = [
            target
            for panel in payload.get("panels", [])
            if (panel.get("datasource") or {}).get("type") == "cloudwatch"
            for target in panel.get("targets", [])
        ]
        self.assertTrue(cloudwatch_targets)
        for target in cloudwatch_targets:
            dimensions = target.get("dimensions") or {}
            self.assertTrue(dimensions)
            self.assertNotIn("", dimensions.values())
            self.assertTrue(all(isinstance(value, str) and value.startswith("$") for value in dimensions.values()))

    def test_eks_dashboard_contains_scale_and_bottleneck_panels_with_short_windows(self):
        payload = json.loads(EKS_DASHBOARD.read_text(encoding="utf-8"))
        titles = {panel.get("title") for panel in payload.get("panels", [])}
        for expected in (
            "Backend Pod health / restart / OOM",
            "ALB request / target health / 5xx",
            "EKS node-group / ASG capacity",
            "RDS / Redis pressure",
        ):
            self.assertIn(expected, titles)
        self.assertNotIn("[5m]", json.dumps(payload))
        names = {item.get("name") for item in payload.get("templating", {}).get("list", [])}
        self.assertTrue({"alb_dimension", "target_group_dimension", "autoscaling_group_name", "db_instance_identifier", "cache_cluster_id"} <= names)

    def test_eks_required_query_contract_covers_every_dashboard_target(self):
        dashboard = json.loads(EKS_DASHBOARD.read_text(encoding="utf-8"))
        contract = json.loads(EKS_QUERY_CONTRACT.read_text(encoding="utf-8"))
        target_keys = {
            f"{panel.get('id')}/{target.get('refId')}"
            for panel in dashboard.get("panels", [])
            for target in panel.get("targets", [])
            if target.get("refId")
        }
        contract_keys = {item.get("key") for item in contract.get("queries", [])}
        self.assertEqual(target_keys, contract_keys)


if __name__ == "__main__":
    unittest.main()
