import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
DASHBOARD = ROOT / "monitoring/grafana/dashboards/aws-recovery.json"


class AwsRecoveryDashboardContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    def test_fixed_recovery_uid_and_annotation(self):
        self.assertEqual(self.payload["uid"], "aws-recovery")
        tags = [item.get("target", {}).get("tags", []) for item in self.payload["annotations"]["list"]]
        self.assertIn("scenario:AWS-RECOVERY", [tag for group in tags for tag in group])
        self.assertNotIn("scenario:B-01", json.dumps(self.payload))

    def test_panel_ids_and_datasources_are_stable(self):
        panels = self.payload["panels"]
        self.assertEqual(len({panel["id"] for panel in panels}), len(panels))
        found = {
            panel.get("datasource", {}).get("uid")
            for panel in panels
            if panel.get("datasource", {}).get("uid") not in {"-- Dashboard --", "-- Grafana --"}
        }
        self.assertTrue({"prometheus", "cloudwatch", "loki"}.issubset(found))

    def test_cloudwatch_dimensions_are_runtime_scoped(self):
        for panel in self.payload["panels"]:
            for target in panel.get("targets", []):
                if target.get("namespace"):
                    dimensions = target.get("dimensions") or {}
                    self.assertTrue(dimensions)
                    self.assertTrue(all(str(value).startswith("$") for value in dimensions.values()))

    def test_recovery_dashboard_has_no_run_id_metric_label(self):
        variables = {item.get("name") for item in self.payload["templating"]["list"]}
        self.assertNotIn("run_id", variables)
        self.assertNotIn('"runId"', json.dumps(self.payload))


if __name__ == "__main__":
    unittest.main()
