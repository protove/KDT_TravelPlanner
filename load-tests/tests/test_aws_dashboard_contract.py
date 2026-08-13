import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPOSITORY_ROOT / "monitoring/grafana/dashboards/aws-load-test.json"


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


if __name__ == "__main__":
    unittest.main()
