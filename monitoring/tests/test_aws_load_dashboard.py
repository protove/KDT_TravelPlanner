"""Schema/panel-ID tests for monitoring/grafana/dashboards/aws-load-test.json,
per aws-load-test-handoff/plans/04_GRAFANA_DASHBOARD_PLAN.md's "검증" list.

These are static checks only — they do not require a live Grafana/Prometheus
(the Plan itself says this dashboard isn't "구현 완료" until D-002/D-003 are
approved and wired; this test suite verifies what's verifiable without that).
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = REPO_ROOT / "monitoring" / "grafana" / "dashboards" / "aws-load-test.json"
BACKEND_OVERVIEW_PATH = REPO_ROOT / "monitoring" / "grafana" / "dashboards" / "backend-overview.json"
EC2_DATASOURCES_PATH = REPO_ROOT / "monitoring" / "ec2" / "datasources.yml"

EXPECTED_DATASOURCE_UIDS = {"prometheus", "loki", "cloudwatch"}


def load_dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


class DashboardJsonValidityTest(unittest.TestCase):
    def test_is_valid_json(self):
        # Mirrors monitoring/validate-configs.sh's `python3 -m json.tool` check
        # for backend-overview.json.
        load_dashboard()  # must not raise

    def test_does_not_overwrite_backend_overview(self):
        dashboard = load_dashboard()
        backend_overview = json.loads(BACKEND_OVERVIEW_PATH.read_text(encoding="utf-8"))
        self.assertNotEqual(dashboard["uid"], backend_overview["uid"])
        self.assertNotEqual(dashboard["title"], backend_overview["title"])


class DashboardStructureTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = load_dashboard()

    def test_has_a_fixed_uid_not_null(self):
        self.assertEqual(self.dashboard["uid"], "aws-load-test-b01")

    def test_panel_ids_are_unique_and_stable(self):
        # "이미지 Export 대상으로 사용할 Panel ID가 고정됨" (Plan04 완료 조건):
        # PNG capture needs a durable Panel ID per panel — collisions or a
        # missing id would break that contract silently.
        panel_ids = [panel["id"] for panel in self.dashboard["panels"]]
        self.assertEqual(len(panel_ids), len(set(panel_ids)), "panel ids must be unique")
        self.assertTrue(all(isinstance(pid, int) for pid in panel_ids))

    def test_only_expected_datasource_uids_are_used(self):
        # UID와 datasource UID가 기대값과 일치 (Plan04 검증). Also covers the
        # dashboard-builtin annotation datasource ("-- Grafana --") and the
        # markdown panel's ("-- Dashboard --" is a text-panel sentinel, not a
        # real datasource query), both excluded from the real-datasource set.
        sentinel_uids = {"-- Grafana --", "-- Dashboard --"}
        found = set()
        for panel in self.dashboard["panels"]:
            uid = panel.get("datasource", {}).get("uid")
            if uid and uid not in sentinel_uids:
                found.add(uid)
            for target in panel.get("targets", []):
                target_uid = target.get("datasource", {}).get("uid")
                if target_uid and target_uid not in sentinel_uids:
                    found.add(target_uid)
        self.assertTrue(found, "expected at least one panel with a real datasource")
        self.assertTrue(found.issubset(EXPECTED_DATASOURCE_UIDS), found)

    def test_datasource_uids_match_provisioned_datasources(self):
        # Cross-check against the actual EC2 datasources.yml so a typo'd UID
        # (e.g. "Prometheus" vs "prometheus") is caught before it ships.
        provisioned_uids = set(re.findall(r"^\s*uid:\s*(\S+)\s*$", EC2_DATASOURCES_PATH.read_text(encoding="utf-8"), re.MULTILINE))
        self.assertTrue(EXPECTED_DATASOURCE_UIDS.issubset(provisioned_uids))

    def test_run_id_is_never_a_template_variable_or_metric_label(self):
        # RUN_METADATA_CONTRACT.md / Plan04 "변수와 시간": Run ID must be
        # carried only by Annotations + a fixed UTC range, never as a metric
        # label across the whole application.
        variable_names = {variable["name"] for variable in self.dashboard["templating"]["list"]}
        self.assertNotIn("run_id", variable_names)
        self.assertNotIn("runId", variable_names)
        serialized = json.dumps(self.dashboard)
        self.assertNotIn('"runId"', serialized)

    def test_dynamic_user_travel_request_ids_are_not_variables(self):
        variable_names = {variable["name"] for variable in self.dashboard["templating"]["list"]}
        self.assertTrue(variable_names.isdisjoint({"user_id", "travel_id", "request_id"}))

    def test_template_variables_include_safe_labels_and_cloudwatch_dimensions(self):
        # Plan04 labels plus non-secret CloudWatch resource dimension
        # placeholders resolved from aws/resource-dimensions.json at export.
        variable_names = {variable["name"] for variable in self.dashboard["templating"]["list"]}
        self.assertEqual(variable_names, {
            "environment", "version", "instance", "availability_zone", "route",
            "alb_dimension", "target_group_dimension", "autoscaling_group_name",
            "db_instance_identifier", "cache_cluster_id",
        })

    def test_cloudwatch_panels_have_no_hardcoded_resource_dimensions(self):
        # "CloudWatch resource dimension이 다른 환경으로 새지 않음" (Plan04
        # 검증): a hardcoded ASG/ALB/RDS/Redis identifier here would silently
        # point every environment's dashboard at one fixed dev resource.
        # Dimensions must use a template variable resolved from the target
        # validation artifact; an empty dimension would issue an unscoped
        # metric query.
        for panel in self.dashboard["panels"]:
            for target in panel.get("targets", []):
                if "namespace" not in target:
                    continue
                dimensions = target.get("dimensions", {})
                self.assertTrue(dimensions, f"panel {panel['id']} must have scoped CloudWatch dimensions")
                self.assertTrue(
                    all(isinstance(value, str) and value.startswith("$") for value in dimensions.values()),
                    f"panel {panel['id']} has hardcoded CloudWatch dimensions: {dimensions}",
                )

    def test_no_user_flow_deep_diagnostic_panels(self):
        # Plan04: rows 8-11 (flow starts/completed/E2E, flow_id/flow_step) are
        # for workloadModel=user-flow deep diagnostics only, not the EC2
        # baseline B-01 platform comparison this dashboard is for.
        serialized = json.dumps(self.dashboard)
        for forbidden in ("flow_id", "flow_step", "flowsCompleted", "flowsStarted"):
            self.assertNotIn(forbidden, serialized)

    def test_annotations_include_b01_run_events_query(self):
        tags_queries = [
            entry.get("target", {}).get("tags", [])
            for entry in self.dashboard["annotations"]["list"]
            if "target" in entry
        ]
        self.assertTrue(any("scenario:B-01" in tags for tags in tags_queries))

    def test_time_range_is_not_hardcoded_to_a_specific_run(self):
        # The default time range is a UI convenience only — the real range
        # for a given run comes from that run's metadata.json, set manually
        # by the operator (Plan04/RUN_METADATA_CONTRACT.md).
        self.assertEqual(self.dashboard["time"], {"from": "now-1h", "to": "now"})

    def test_all_panels_have_a_title(self):
        for panel in self.dashboard["panels"]:
            self.assertTrue(panel.get("title"), f"panel {panel.get('id')} has no title")


if __name__ == "__main__":
    unittest.main()
