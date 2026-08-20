from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
PROFILE = ROOT / "load-tests/sql-diagnostic-profile.json"
SEEDER = ROOT / "scripts/loadtest/seed-compose-sql-diagnostic-data.py"
K6_FLOW = ROOT / "load-tests/k6/flows/sql-round-trip-diagnostic.js"
K6_SCENARIO = ROOT / "load-tests/k6/scenarios/sql-round-trip-diagnostic.js"


class SqlRoundTripDiagnosticContractTest(unittest.TestCase):
    def test_profile_matches_manifest_sweep(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(profile["itemCounts"], [3, 10, 25, 50, 100, 200])
        self.assertEqual(profile["modes"], ["noop", "reverse"])
        self.assertEqual(profile["warmupIterations"], 4)
        self.assertEqual(profile["measuredIterations"], 30)
        self.assertEqual(profile["replicates"], 3)
        self.assertEqual(len(profile["queryFamilies"]), 6)

    def test_replicate_orders_cover_every_stage_without_duplication(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        expected_counts = set(profile["itemCounts"])
        for replicate in ("1", "2", "3"):
            order = profile["orderByReplicate"][replicate]["itemCounts"]
            self.assertEqual(len(order), len(expected_counts))
            self.assertEqual(set(order), expected_counts)

    def test_required_focused_artifacts_exist(self) -> None:
        for path in (PROFILE, SEEDER, K6_FLOW, K6_SCENARIO):
            self.assertTrue(path.is_file(), path)

    def test_k6_flow_contains_noop_reverse_and_bounded_labels(self) -> None:
        source = K6_FLOW.read_text(encoding="utf-8")
        self.assertIn("mode === 'noop'", source)
        self.assertIn("canonical.slice().reverse()", source)
        self.assertIn("sql_diagnostic_item_count", source)
        self.assertNotIn("sql_diagnostic_item_id", source)
        self.assertNotIn("request_id", source)

    def test_scenario_is_single_vu_shared_iterations(self) -> None:
        source = K6_SCENARIO.read_text(encoding="utf-8")
        self.assertIn("executor: 'shared-iterations'", source)
        self.assertIn("vus: 1", source)


if __name__ == "__main__":
    unittest.main()
