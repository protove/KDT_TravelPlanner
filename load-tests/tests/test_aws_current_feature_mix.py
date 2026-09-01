import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "load-tests/aws/profiles/eks-monolith-breakpoint-v2.0.json"
PROFILE_V21 = ROOT / "load-tests/aws/profiles/eks-monolith-breakpoint-v2.1.json"
FLOW = ROOT / "load-tests/k6/aws/flows/current-feature-operations.js"

EXPECTED_WEIGHTS = {
    "refresh": 5,
    "profileRead": 3,
    "travelList": 8,
    "travelDetail": 8,
    "travelUpdate": 4,
    "countryList": 1,
    "cityList": 1,
    "placeSearch": 4,
    "nearbySearch": 2,
    "mapPoints": 4,
    "routeGet": 3,
    "routePreview": 3,
    "timelineCreate": 8,
    "orderChange": 6,
    "memberList": 3,
    "invitationList": 3,
    "communityCategoryList": 2,
    "communityPostList": 8,
    "communityPostDetail": 5,
    "communityCommentList": 4,
    "communityMyPosts": 2,
    "communityMyComments": 1,
    "communityPostUpdate": 3,
    "communityCommentUpdate": 3,
    "communityPostReaction": 3,
    "communityCommentReaction": 3,
}


class CurrentFeatureMixTest(unittest.TestCase):
    def test_profile_has_one_frozen_mix_for_normal_baseline_and_stress(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(profile["requestMixVersion"], "aws-eks-current-feature-coverage-v2")
        self.assertEqual(profile["requestMix"]["normal"], EXPECTED_WEIGHTS)
        for name in ("baseline", "spike", "soak"):
            self.assertEqual(profile["requestMix"][name], EXPECTED_WEIGHTS)
        self.assertEqual(sum(EXPECTED_WEIGHTS.values()), 100)

    def test_v21_profile_reuses_the_same_current_feature_mix(self):
        profile = json.loads(PROFILE_V21.read_text(encoding="utf-8"))
        self.assertEqual(profile["requestMixVersion"], "aws-eks-current-feature-coverage-v2")
        for name in ("normal", "baseline", "spike", "soak"):
            self.assertEqual(profile["requestMix"][name], EXPECTED_WEIGHTS)
        self.assertEqual(profile["eks"]["instanceType"], "t3.medium")

    def test_flow_declares_every_profile_operation_and_bounded_metrics(self):
        source = FLOW.read_text(encoding="utf-8")
        declared = set(re.findall(r"\{ id: '([^']+)', weight:", source))
        self.assertEqual(declared, set(EXPECTED_WEIGHTS))
        for operation in EXPECTED_WEIGHTS:
            self.assertIn("new Counter(`aws_operation_${operation.id}_selected_total`)", source)
            self.assertIn(f"operationId,", source)
        self.assertIn("observedWeight", source)
        self.assertIn("recordCoreOperation", source)

    def test_google_adapters_are_only_reached_by_backend_mock_contract(self):
        source = FLOW.read_text(encoding="utf-8")
        self.assertNotIn("googleapis.com", source)
        self.assertIn("placeSearch", source)
        self.assertIn("routePreview", source)
        self.assertIn("current-feature", source)

    def test_timeline_create_uses_unassigned_fixture_without_growing_route_day(self):
        source = FLOW.read_text(encoding="utf-8")
        self.assertIn("dayNumber: null", source)
        self.assertIn("visitDate: null", source)
        self.assertIn("three-item day-1 fixture", source)


if __name__ == "__main__":
    unittest.main()
