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

    def test_recovery_accepts_ca_desired_four_with_canonical_bounds(self) -> None:
        payload = json.loads(json.dumps(self.fixture["nodeGroup"]))
        payload["nodegroup"]["scalingConfig"]["desiredSize"] = 4
        node_group = MODULE.resolve_node_group(
            payload,
            expected_cluster=self.fixture["clusterName"],
            expected_node_group=self.fixture["nodeGroupName"],
            allow_current_desired=True,
        )
        self.assertEqual(node_group["scalingConfig"], {"min": 2, "desired": 4, "max": 4})

    def test_fresh_target_still_rejects_noncanonical_desired(self) -> None:
        payload = json.loads(json.dumps(self.fixture["nodeGroup"]))
        payload["nodegroup"]["scalingConfig"]["desiredSize"] = 4
        with self.assertRaisesRegex(MODULE.EKSAdapterError, "must be 2/2/4"):
            MODULE.resolve_node_group(
                payload,
                expected_cluster=self.fixture["clusterName"],
                expected_node_group=self.fixture["nodeGroupName"],
            )

    def test_instance_id_target_is_rejected_in_eks_mode(self) -> None:
        payload = json.loads(json.dumps(self.fixture["targetHealth"]))
        payload["TargetHealthDescriptions"][0]["Target"]["Id"] = "i-0123456789abcdef0"
        with self.assertRaises(MODULE.EKSAdapterError):
            MODULE.validate_alb_target_health(payload, target_group_arn=self.fixture["targetGroupArn"])

    def test_observer_can_preserve_an_all_unhealthy_alb_snapshot(self) -> None:
        payload = json.loads(json.dumps(self.fixture["targetHealth"]))
        for item in payload["TargetHealthDescriptions"]:
            item["TargetHealth"]["State"] = "unhealthy"
        summary = MODULE.validate_alb_target_health(
            payload,
            target_group_arn=self.fixture["targetGroupArn"],
            allow_no_healthy=True,
        )
        self.assertEqual(summary["healthyTargetCount"], 0)
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
        for resource in ("hpa", "deployment", "pods", "all_pods", "nodes", "events"):
            self.assertIn(f"__SCRUM53_{resource.upper()}_BEGIN__", joined)
            self.assertIn(f"kubectl", joined)
        self.assertNotIn("delete", joined.lower())
        self.assertNotIn("kubectl apply", joined.lower())
        self.assertNotIn("secret", joined.lower())
        self.assertIn("app.kubernetes.io/name=travel-planner-backend", joined)
        self.assertIn("jq -c", joined)
        self.assertLess(joined.index("__SCRUM53_NODES_BEGIN__"), joined.index("__SCRUM53_ALL_PODS_BEGIN__"))

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
        self.assertEqual(evidence["hpa"]["availableReplicas"], 2)
        self.assertEqual(evidence["backendPods"]["count"], 2)
        self.assertEqual(evidence["backendPods"]["readyCount"], 2)
        self.assertEqual(evidence["backendPods"]["restartCount"], 1)
        self.assertEqual(len(evidence["backendPods"]["imageIds"]), 2)
        self.assertEqual(evidence["nodeCount"], 2)
        self.assertEqual(len(evidence["nodeGroupScalingActivities"]), 1)
        self.assertEqual(evidence["alb"]["healthyTargetCount"], 2)
        self.assertTrue(evidence["sanitization"]["rawKubectlOutputStored"] is False)

    def test_evidence_exposes_hpa_ceiling_and_backend_failure_signals(self) -> None:
        kubectl = json.loads(json.dumps(self.fixture["kubectl"]))
        kubectl["hpa"]["spec"] = {"minReplicas": 2, "maxReplicas": 4}
        kubectl["deployment"]["status"]["unavailableReplicas"] = 1
        kubectl["pods"]["items"][0]["status"]["containerStatuses"][0]["lastState"] = {
            "terminated": {"reason": "OOMKilled"}
        }
        kubectl["pods"]["items"][1]["status"]["containerStatuses"][0]["state"] = {
            "waiting": {"reason": "CrashLoopBackOff"}
        }
        evidence = MODULE.build_evidence(
            node_group=MODULE.resolve_node_group(self.fixture["nodeGroup"], expected_cluster=self.fixture["clusterName"], expected_node_group=self.fixture["nodeGroupName"]),
            target_health=MODULE.validate_alb_target_health(self.fixture["targetHealth"], target_group_arn=self.fixture["targetGroupArn"]),
            hpa=kubectl["hpa"], deployment=kubectl["deployment"], pods=kubectl["pods"], nodes=kubectl["nodes"], events=kubectl["events"], asg_activities=self.fixture["asgActivities"],
        )
        self.assertEqual(evidence["hpa"]["maxReplicas"], 4)
        self.assertEqual(evidence["deployment"]["unavailableReplicas"], 1)
        self.assertTrue(evidence["backendPods"]["placement"][0]["oomKilled"])
        self.assertTrue(evidence["backendPods"]["placement"][1]["crashLoopBackOff"])

    def test_high_watermark_preserves_observed_capacity_when_a_phase_is_skipped(self) -> None:
        previous = {"nodeCount": 2, "nodeReadyCount": 2, "backendPods": {"count": 2, "readyCount": 2}}
        current = {"nodeCount": 1, "nodeReadyCount": 1, "backendPods": {"count": 1, "readyCount": 0}}
        result = MODULE.high_watermark(previous, current)
        self.assertEqual(result["nodeCount"], 2)
        self.assertEqual(result["backendPods"]["readyCount"], 2)

    def test_capacity_curve_uses_allocatable_requests_and_renders_n4_plus_one(self) -> None:
        nodes = {
            "items": [
                {"metadata": {"name": "node-a"}, "status": {
                    "allocatable": {"cpu": "2", "memory": "4Gi", "pods": "20"},
                    "conditions": [{"type": "Ready", "status": "True"}],
                }},
                {"metadata": {"name": "node-b"}, "status": {
                    "allocatable": {"cpu": "2", "memory": "4Gi", "pods": "20"},
                    "conditions": [{"type": "Ready", "status": "True"}],
                }},
            ]
        }
        deployment = {"spec": {"template": {"spec": {"containers": [
            {"name": "backend", "resources": {"requests": {"cpu": "500m", "memory": "512Mi"}}},
        ]}}}}
        curve = MODULE.calculate_capacity_curve(nodes, deployment)
        self.assertTrue(curve["valid"])
        self.assertEqual(curve["N1"], 4)
        self.assertEqual(curve["N2"], 8)
        self.assertEqual(curve["N4"], 16)
        patch = MODULE.build_hpa_override(curve)
        self.assertEqual(patch["spec"]["maxReplicas"], 17)

    def test_hpa_apply_receipt_is_bound_to_run_scoped_n4_plus_one(self) -> None:
        invocation = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": (
                "deployment.apps/backend configured\n"
                "__SCRUM80_HPA_APPLY_BEGIN__\n"
                '{"metadata":{"name":"backend","namespace":"travel-planner",'
                '"annotations":{"load-test.kdt.travelplanner/scope":"run-scoped-n4-plus-one",'
                '"load-test.kdt.travelplanner/n4":"16"}},'
                '"spec":{"minReplicas":2,"maxReplicas":17}}\n'
                "__SCRUM80_HPA_APPLY_END__\n"
            ),
            "StandardErrorContent": "",
        }
        receipt = MODULE.sanitize_hpa_apply_invocation(
            invocation,
            expected_max_replicas=17,
            override_sha256="a" * 64,
        )
        self.assertEqual(receipt["maxReplicas"], 17)
        self.assertEqual(receipt["n4"], "16")
        self.assertFalse(receipt["rawOutputStored"])

    def test_hpa_apply_receipt_rejects_canonical_four_pod_ceiling(self) -> None:
        invocation = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": (
                "__SCRUM80_HPA_APPLY_BEGIN__\n"
                '{"metadata":{"name":"backend","namespace":"travel-planner",'
                '"annotations":{"load-test.kdt.travelplanner/scope":"run-scoped-n4-plus-one"}},'
                '"spec":{"minReplicas":2,"maxReplicas":4}}\n'
                "__SCRUM80_HPA_APPLY_END__\n"
            ),
        }
        with self.assertRaises(MODULE.EKSAdapterError):
            MODULE.sanitize_hpa_apply_invocation(
                invocation,
                expected_max_replicas=4,
                override_sha256="a" * 64,
            )

    def test_pending_backend_pod_is_separate_from_node_scale_out(self) -> None:
        kubectl = json.loads(json.dumps(self.fixture["kubectl"]))
        kubectl["pods"]["items"].append({
            "metadata": {"name": "backend-pending"},
            "spec": {},
            "status": {"phase": "Pending", "reason": "FailedScheduling", "conditions": [{"reason": "Insufficient cpu"}]},
        })
        evidence = MODULE.build_evidence(
            node_group=MODULE.resolve_node_group(self.fixture["nodeGroup"], expected_cluster=self.fixture["clusterName"], expected_node_group=self.fixture["nodeGroupName"]),
            target_health=MODULE.validate_alb_target_health(self.fixture["targetHealth"], target_group_arn=self.fixture["targetGroupArn"]),
            hpa=kubectl["hpa"], deployment=kubectl["deployment"], pods=kubectl["pods"], nodes=kubectl["nodes"], events=kubectl["events"], asg_activities=self.fixture["asgActivities"],
        )
        self.assertEqual(evidence["backendPods"]["pendingCount"], 1)
        self.assertIn("FailedScheduling", evidence["backendPods"]["pendingReasons"])
        self.assertFalse(evidence["nodeScaleOut"] if "nodeScaleOut" in evidence else False)
        self.assertFalse(evidence["maxCapacityReached"])

    def test_fixture_has_no_credentials_private_ips_or_live_account_ids(self) -> None:
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertNotIn("password", text.lower())
        self.assertNotIn("secret", text.lower())
        self.assertIn("000000000000", text)
        self.assertIn("192.0.2.", text)
        self.assertNotIn("10.", text)


if __name__ == "__main__":
    unittest.main()
