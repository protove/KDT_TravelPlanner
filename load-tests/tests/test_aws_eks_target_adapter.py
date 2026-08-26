from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/loadtest/aws/eks_target_adapter.py"
SPEC = importlib.util.spec_from_file_location("eks_target_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

FIXTURE = ROOT / "load-tests/aws/fixtures/eks-target.json"


class EksTargetAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_resolves_managed_node_group_not_alb_pod_targets(self) -> None:
        node_group = MODULE.resolve_node_group(
            self.fixture["nodeGroup"],
            expected_cluster=self.fixture["clusterName"],
            expected_node_group=self.fixture["nodeGroupName"],
        )
        target_health = MODULE.validate_alb_target_health(
            self.fixture["targetHealth"], target_group_arn=self.fixture["targetGroupArn"],
        )
        self.assertEqual(node_group["scalingConfig"], {"min": 2, "desired": 2, "max": 4})
        self.assertEqual(node_group["autoScalingGroupName"], "eks-example-nodegroup-asg")
        self.assertEqual(target_health["targetType"], "ip")
        self.assertEqual(target_health["healthyTargetCount"], 2)

    def test_instance_id_target_is_rejected_in_eks_mode(self) -> None:
        payload = json.loads(json.dumps(self.fixture["targetHealth"]))
        payload["TargetHealthDescriptions"][0]["Target"]["Id"] = "i-0123456789abcdef0"
        with self.assertRaises(MODULE.EKSAdapterError):
            MODULE.validate_alb_target_health(payload, target_group_arn=self.fixture["targetGroupArn"])

    def test_kubectl_commands_are_read_only_and_cover_required_snapshots(self) -> None:
        commands = MODULE.build_kubectl_commands(
            cluster_name="example-dev-eks",
            region="ap-northeast-2",
            namespace="travel-planner",
            deployment="backend",
        )
        joined = "\n".join(commands)
        for resource in ("hpa", "deployment", "pods", "nodes", "events"):
            self.assertIn(f"__SCRUM53_{resource.upper()}_BEGIN__", joined)
            self.assertIn(f"kubectl", joined)
        self.assertNotIn("delete", joined.lower())
        self.assertNotIn("kubectl apply", joined.lower())
        self.assertNotIn("secret", joined.lower())
        self.assertIn("app.kubernetes.io/name=travel-planner-backend", joined)

    def test_evidence_contains_hpa_pod_node_scaling_and_alb_dimensions(self) -> None:
        node_group = MODULE.resolve_node_group(
            self.fixture["nodeGroup"],
            expected_cluster=self.fixture["clusterName"],
            expected_node_group=self.fixture["nodeGroupName"],
        )
        target_health = MODULE.validate_alb_target_health(
            self.fixture["targetHealth"], target_group_arn=self.fixture["targetGroupArn"],
        )
        kubectl = self.fixture["kubectl"]
        evidence = MODULE.build_evidence(
            node_group=node_group,
            target_health=target_health,
            hpa=kubectl["hpa"],
            deployment=kubectl["deployment"],
            pods=kubectl["pods"],
            nodes=kubectl["nodes"],
            events=kubectl["events"],
            asg_activities=self.fixture["asgActivities"],
        )
        self.assertEqual(evidence["hpa"]["desiredReplicas"], 2)
        self.assertEqual(evidence["hpa"]["currentReplicas"], 2)
        self.assertEqual(evidence["backendPods"]["count"], 2)
        self.assertEqual(evidence["nodeCount"], 2)
        self.assertEqual(len(evidence["nodeGroupScalingActivities"]), 1)
        self.assertEqual(evidence["alb"]["healthyTargetCount"], 2)
        self.assertTrue(evidence["sanitization"]["rawKubectlOutputStored"] is False)

    def test_fixture_has_no_credentials_private_ips_or_live_account_ids(self) -> None:
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertNotIn("password", text.lower())
        self.assertNotIn("secret", text.lower())
        self.assertIn("000000000000", text)
        self.assertIn("192.0.2.", text)
        self.assertNotIn("10.", text)


if __name__ == "__main__":
    unittest.main()
