from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = ROOT / "scripts/loadtest/aws/run-msa-boundary-campaign.py"
ANALYSIS_PATH = ROOT / "scripts/loadtest/aws/analyze-msa-boundary-campaign.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


CAMPAIGN = load_module(CAMPAIGN_PATH, "msa_boundary_campaign")
ANALYSIS = load_module(ANALYSIS_PATH, "msa_boundary_analysis")


class AwsMsaBoundaryCampaignTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads((ROOT / "load-tests/aws/profiles/eks-monolith-msa-boundary-v1.0.json").read_text())
        self.operation_map = json.loads((ROOT / "load-tests/aws/contracts/msa-boundary-operation-map-v1.0.json").read_text())

    def test_dry_run_order_has_balanced_hotspot_spike_recovery_without_ceiling(self) -> None:
        plan = CAMPAIGN.build_campaign_plan(self.profile, self.operation_map, ["maps", "community"])
        ids = [stage["id"] for stage in plan["stages"]]
        self.assertEqual(ids[:2], ["smoke", "baseline-16"])
        self.assertEqual(ids[2:7], ["balanced-64", "balanced-128", "balanced-192", "balanced-224", "balanced-256"])
        self.assertEqual(ids[7:], ["hotspot-1", "hotspot-2", "spike-256", "recovery-16"])
        self.assertEqual(plan["stages"][7]["holdSeconds"], 300)
        self.assertEqual(plan["stages"][-1]["totalObservationSeconds"], 1200)
        self.assertTrue(plan["noHiddenRpsCeiling"])

    def test_invalid_candidate_or_duplicate_endpoint_fails_closed(self) -> None:
        with self.assertRaises(CAMPAIGN.CampaignError):
            CAMPAIGN.build_campaign_plan(self.profile, self.operation_map, ["unknown", "maps"])
        operation_map = json.loads(json.dumps(self.operation_map))
        operation_map["operations"][1]["route"] = operation_map["operations"][0]["route"]
        operation_map["operations"][1]["method"] = operation_map["operations"][0]["method"]
        with self.assertRaises(CAMPAIGN.CampaignError):
            CAMPAIGN.validate_operation_map(self.profile, operation_map)

    def test_output_file_is_deterministic_and_does_not_touch_aws(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "campaign.json"
            plan = CAMPAIGN.build_campaign_plan(self.profile, self.operation_map)
            output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
            self.assertEqual(json.loads(output.read_text()), plan)


class AwsMsaBoundaryAnalysisTest(unittest.TestCase):
    def test_ranker_selects_two_complete_candidates_with_stable_tie_break(self) -> None:
        records = [
            {"candidate": "community", "complete": True, "sloBreachWindows": 1, "p95SloRatio": 2.0, "errorRate": 0.1, "droppedRate": 0.0, "driverScore": 1.0},
            {"candidate": "maps", "complete": True, "sloBreachWindows": 2, "p95SloRatio": 1.1, "errorRate": 0.0, "droppedRate": 0.0, "driverScore": 0.2},
            {"candidate": "travel", "complete": False, "sloBreachWindows": 9, "p95SloRatio": 9.0},
        ]
        result = ANALYSIS.select_top_two(records, ["identity", "travel", "maps", "community"])
        self.assertEqual(result["selected"], ["maps", "community"])

    def test_incomplete_records_cannot_be_promoted_to_hotspot(self) -> None:
        with self.assertRaises(ANALYSIS.AnalysisError):
            ANALYSIS.select_top_two([{"candidate": "maps", "complete": False}], ["maps", "community"])

    def test_evidence_mode_scores_operation_tagged_windows_and_selects_highest_stable_rate(self) -> None:
        profile = json.loads((ROOT / "load-tests/aws/profiles/eks-monolith-msa-boundary-v1.0.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for rate, p95 in ((64, 40), (128, 80), (192, 700)):
                stage = root / "k6" / f"balanced-{rate}"
                stage.mkdir(parents=True)
                (stage / "controller-result.json").write_text(json.dumps({"terminalReason": "STAGE_COMPLETE"}))
                (stage / "capacity-stress-result.json").write_text(json.dumps({
                    "snapshotWindow": {"completeSloWindows": 2, "sloBreachedWindows": 0 if rate < 192 else 1},
                    "runner": {"invalid": False}, "mock": {"validity": "VALID"},
                }))
                points = []
                for candidate, value in (("travel-timeline", p95), ("travel-membership", value := 100)):
                    points.append(json.dumps({
                        "metric": "http_req_duration", "type": "Point",
                        "data": {"value": value, "tags": {"subdomain": candidate, "status": "200"}},
                    }))
                (stage / "raw.json").write_text("\n".join(points) + "\n")
            payload = ANALYSIS.build_candidate_metrics(root, profile)
            self.assertEqual(payload["source"]["highestStableRate"], 128)
            result = ANALYSIS.select_top_two(payload["candidateMetrics"], payload["candidateOrder"])
            self.assertEqual(result["selected"], ["travel-timeline", "travel-membership"])


if __name__ == "__main__":
    unittest.main()
