import copy
import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts/loadtest/aws/validate-aws-profile.py"
SPEC = importlib.util.spec_from_file_location("validate_aws_profile", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

PROFILE_PATH = Path(__file__).parents[1] / "aws/profiles/ec2-b01.json"


def load_repo_profile():
    return MODULE.load_profile(PROFILE_PATH)


class AwsLoadProfileTest(unittest.TestCase):
    def test_repo_profile_file_is_valid(self):
        profile = load_repo_profile()
        self.assertTrue(MODULE.validate(profile))

    def test_missing_required_field_is_rejected(self):
        profile = load_repo_profile()
        del profile["sloVersion"]
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_non_https_target_is_rejected(self):
        profile = load_repo_profile()
        profile["target"]["baseUrl"] = "http://insecure.example.com"
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_placeholder_target_is_allowed_at_the_profile_level(self):
        # The committed template intentionally ships a REPLACE_ placeholder;
        # only load-tests/k6/aws/config.js at k6 runtime enforces that the
        # operator has actually supplied BASE_URL before traffic is sent.
        profile = load_repo_profile()
        profile["target"]["baseUrl"] = "https://REPLACE_WITH_APPROVED_ALB_HOSTNAME"
        self.assertTrue(MODULE.validate(profile))

    def test_google_api_enabled_is_rejected(self):
        profile = load_repo_profile()
        profile["googleApi"]["enabled"] = True
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_k6_image_without_digest_is_rejected(self):
        profile = load_repo_profile()
        profile["k6Image"] = "grafana/k6:0.54.0"
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_k6_image_with_digest_is_accepted(self):
        profile = load_repo_profile()
        profile["k6Image"] = "grafana/k6:0.54.0@sha256:" + "a" * 64
        self.assertTrue(MODULE.validate(profile))

    def test_ramp_stage_rate_above_limit_is_rejected(self):
        profile = load_repo_profile()
        profile["scenarios"]["ramp"]["stages"][0]["targetRate"] = profile["limits"]["maxRate"] + 1
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_ramp_max_vus_above_limit_is_rejected(self):
        profile = load_repo_profile()
        profile["scenarios"]["ramp"]["maxVUs"] = profile["limits"]["maxVUs"] + 1
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_baseline_null_rate_is_accepted_pending_d005(self):
        profile = load_repo_profile()
        profile["scenarios"]["baseline"]["rate"] = None
        self.assertTrue(MODULE.validate(profile))

    def test_baseline_negative_rate_is_rejected(self):
        profile = load_repo_profile()
        profile["scenarios"]["baseline"]["rate"] = -1
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_spike_multiplier_must_exceed_one(self):
        profile = load_repo_profile()
        profile["scenarios"]["spike"]["peakRateMultiplier"] = 1
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_request_mix_baseline_must_sum_to_100(self):
        profile = load_repo_profile()
        profile["requestMix"]["baseline"]["refresh"] = 999
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_request_mix_spike_must_sum_to_100(self):
        profile = load_repo_profile()
        profile["requestMix"]["spike"]["refresh"] = 999
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_missing_scenario_is_rejected(self):
        profile = load_repo_profile()
        del profile["scenarios"]["spike"]
        with self.assertRaises(ValueError):
            MODULE.validate(profile)

    def test_validate_does_not_mutate_input(self):
        profile = load_repo_profile()
        snapshot = copy.deepcopy(profile)
        MODULE.validate(profile)
        self.assertEqual(profile, snapshot)


if __name__ == "__main__":
    unittest.main()
