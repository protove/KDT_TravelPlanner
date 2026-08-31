from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
PROFILE = ROOT / "load-tests/aws/profiles/ec2-eks-capacity-stress-v1.0.json"
PROFILE_V11 = ROOT / "load-tests/aws/profiles/ec2-eks-capacity-stress-v1.1.json"
EKS_BREAKPOINT_PROFILE = ROOT / "load-tests/aws/profiles/eks-monolith-breakpoint-v1.0.json"
VALIDATOR_PATH = ROOT / "scripts/loadtest/aws/validate-aws-profile.py"
SPEC = importlib.util.spec_from_file_location("validate_aws_profile_capacity", VALIDATOR_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CapacityStressProfileTest(unittest.TestCase):
    def profile(self) -> dict:
        return json.loads(PROFILE.read_text(encoding="utf-8"))

    def test_profile_is_valid_and_preregistered(self) -> None:
        profile = self.profile()
        self.assertTrue(MODULE.validate(profile))
        self.assertEqual(profile["sloVersion"], "v1.1-frozen")
        self.assertEqual(profile["capacityStress"]["stageMultipliers"], [1, 2, 4, 8])
        self.assertEqual(profile["capacityStress"]["maxVUs"], 320)
        self.assertEqual(profile["capacityStress"]["seededUsers"], 320)

    def test_validation_does_not_mutate_profile(self) -> None:
        profile = self.profile()
        before = copy.deepcopy(profile)
        MODULE.validate(profile)
        self.assertEqual(profile, before)

    def test_frozen_slo_is_required(self) -> None:
        profile = self.profile()
        profile["sloVersion"] = "v1.1-candidate"
        with self.assertRaisesRegex(ValueError, "v1.1-frozen"):
            MODULE.validate(profile)

    def test_stage_schedule_is_exact(self) -> None:
        profile = self.profile()
        profile["capacityStress"]["stageMultipliers"] = [1, 2, 3, 4]
        with self.assertRaisesRegex(ValueError, "stageMultipliers"):
            MODULE.validate(profile)

    def test_seeded_users_must_cover_max_vus(self) -> None:
        profile = self.profile()
        profile["capacityStress"]["seededUsers"] = 319
        with self.assertRaisesRegex(ValueError, "seededUsers"):
            MODULE.validate(profile)

    def test_runner_repair_is_bounded_to_one_pair(self) -> None:
        profile = self.profile()
        profile["capacityStress"]["runnerRepairLimit"] = 2
        with self.assertRaisesRegex(ValueError, "exactly one"):
            MODULE.validate(profile)

    def test_v11_profile_is_valid_and_preserves_the_same_stress_bytes(self) -> None:
        profile = json.loads(PROFILE_V11.read_text(encoding="utf-8"))
        self.assertTrue(MODULE.validate(profile))
        stress = profile["capacityStress"]
        self.assertEqual(stress["stageMultipliers"], [1, 2, 4, 8])
        self.assertEqual(stress["stageDurations"], ["5m", "8m", "8m", "8m"])
        self.assertEqual(stress["maxVUs"], 320)
        self.assertEqual(stress["seededUsers"], 320)
        self.assertEqual(profile["sloVersion"], "v1.1-frozen")

    def test_eks_breakpoint_profile_is_monotonic_and_keeps_base_capacity(self) -> None:
        profile = json.loads(EKS_BREAKPOINT_PROFILE.read_text(encoding="utf-8"))
        self.assertTrue(MODULE.validate(profile))
        self.assertEqual(profile["target"]["platform"], "eks")
        self.assertEqual(profile["sloVersion"], "v1.1-candidate")
        self.assertEqual(
            profile["capacityStress"]["bindsTo"]["sloContract"],
            "load-tests/aws/contracts/eks-monolith-breakpoint-slo-v1.0.json",
        )
        self.assertEqual(profile["eks"]["instanceType"], "t3.small")
        self.assertEqual(profile["eks"]["nodeGroup"], {"min": 2, "desired": 2, "max": 4})
        self.assertEqual(profile["eks"]["baseHpa"], {"minReplicas": 2, "maxReplicas": 4})
        multipliers = profile["capacityStress"]["stageMultipliers"]
        self.assertGreaterEqual(len(multipliers), 5)
        self.assertEqual(multipliers, [1, 2, 4, 8, 16])
        self.assertTrue(profile["capacityStress"]["requiresCompleteSloWindows"])

    def test_eks_breakpoint_rejects_non_monotonic_stage(self) -> None:
        profile = json.loads(EKS_BREAKPOINT_PROFILE.read_text(encoding="utf-8"))
        profile["capacityStress"]["stageMultipliers"] = [1, 2, 4, 8, 8]
        with self.assertRaisesRegex(ValueError, "double monotonically"):
            MODULE.validate(profile)


if __name__ == "__main__":
    unittest.main()
