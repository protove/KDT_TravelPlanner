import copy
import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts/loadtest/aws/validate-aws-recovery-profile.py"
SPEC = importlib.util.spec_from_file_location("validate_aws_recovery_profile", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

PROFILE_PATH = Path(__file__).parents[1] / "aws/profiles/ec2-recovery.json"


class AwsRecoveryProfileTest(unittest.TestCase):
    def test_repo_profile_is_valid(self):
        self.assertTrue(MODULE.validate(MODULE.load_profile(PROFILE_PATH)))

    def test_profile_is_independent_of_b01_scenarios(self):
        profile = MODULE.load_profile(PROFILE_PATH)
        self.assertNotIn("scenarios", profile)
        self.assertEqual(profile["scenarioId"], "AWS-RECOVERY")

    def test_recovery_window_contract_is_fixed(self):
        profile = MODULE.load_profile(PROFILE_PATH)
        self.assertEqual(profile["recovery"]["bucketSeconds"], 10)
        self.assertEqual(profile["recovery"]["stableWindowSeconds"], 120)
        self.assertEqual(profile["recovery"]["budgetSeconds"], 600)

    def test_nonzero_contract_failure_threshold_is_rejected(self):
        profile = MODULE.load_profile(PROFILE_PATH)
        profile["recovery"]["contractFailureRate"] = 0.01
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_recovery_vus_above_limit_is_rejected(self):
        profile = MODULE.load_profile(PROFILE_PATH)
        profile["recovery"]["maxVUs"] = profile["limits"]["maxVUs"] + 1
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_validator_does_not_mutate_profile(self):
        profile = MODULE.load_profile(PROFILE_PATH)
        snapshot = copy.deepcopy(profile)
        MODULE.validate(profile)
        self.assertEqual(profile, snapshot)


if __name__ == "__main__":
    unittest.main()
