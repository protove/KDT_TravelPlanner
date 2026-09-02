from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "scripts/loadtest/aws/validate-aws-profile.py"
SPEC = importlib.util.spec_from_file_location("validate_aws_profile_msa", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(VALIDATOR)

PROFILE_PATH = ROOT / "load-tests/aws/profiles/eks-monolith-msa-boundary-v1.0.json"
MAP_PATH = ROOT / "load-tests/aws/contracts/msa-boundary-operation-map-v1.0.json"


class AwsMsaBoundaryProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        self.operation_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def test_profile_validates_without_freezing_an_rps_ceiling(self) -> None:
        self.assertTrue(VALIDATOR.validate(self.profile))
        stress = self.profile["capacityStress"]
        self.assertIsNone(stress["fixedRpsCeiling"])
        self.assertEqual(stress["balancedRates"], [64, 128, 192, 224, 256])
        self.assertEqual(stress["hotspotHoldSeconds"], 300)
        self.assertEqual(stress["recoveryObservationSeconds"], 1200)

    def test_node_and_hpa_envelopes_remain_canonical(self) -> None:
        self.assertEqual(self.profile["eks"]["instanceType"], "t3.medium")
        self.assertEqual(self.profile["eks"]["nodeGroup"], {"min": 2, "desired": 2, "max": 4})
        self.assertEqual(self.profile["eks"]["baseHpa"], {"minReplicas": 2, "maxReplicas": 4})

    def test_operation_map_is_exactly_the_frozen_26_operation_mix(self) -> None:
        operations = self.operation_map["operations"]
        self.assertEqual(len(operations), 26)
        self.assertEqual(sum(item["weight"] for item in operations), 100)
        self.assertEqual(set(item["id"] for item in operations), VALIDATOR.CURRENT_FEATURE_OPERATION_IDS)
        self.assertEqual(set(self.profile["requestMix"]["normal"]), set(item["id"] for item in operations))

    def test_mutating_rate_or_ceiling_is_rejected(self) -> None:
        self.profile["capacityStress"]["balancedRates"] = [64, 128, 256]
        with self.assertRaises(ValueError):
            VALIDATOR.validate(self.profile)


if __name__ == "__main__":
    unittest.main()
