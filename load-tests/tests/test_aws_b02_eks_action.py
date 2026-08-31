from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/actions/b02-eks-node-replacement.py"
SPEC = importlib.util.spec_from_file_location("b02_eks_node_replacement", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class FakeAws:
    def __init__(self) -> None:
        self.mutations: list[tuple[str, str, list[str]]] = []

    def read_json(self, service, operation, arguments):
        if service == "sts":
            return {"Account": "111111111111"}
        if service == "eks":
            return {"nodegroup": {
                "clusterName": MODULE.APPROVED_CLUSTER,
                "nodegroupName": MODULE.APPROVED_NODE_GROUP,
                "status": "ACTIVE",
                "scalingConfig": {"minSize": 2, "desiredSize": 2, "maxSize": 4},
                "resources": {"autoScalingGroups": [{"name": "eks-managed-asg"}]},
            }}
        if service == "autoscaling":
            return {"AutoScalingGroups": [{
                "AutoScalingGroupName": "eks-managed-asg",
                "MinSize": 2, "DesiredCapacity": 2, "MaxSize": 4,
                "Instances": [{"InstanceId": "i-0123456789abcdef0", "LifecycleState": "InService", "HealthStatus": "Healthy"}],
            }]}
        if service == "ec2":
            return {"Reservations": [{"Instances": [{"InstanceId": "i-0123456789abcdef0", "State": {"Name": "running"}, "InstanceType": "t3.small"}]}]}
        if service == "elbv2":
            return {"TargetHealthDescriptions": [{"Target": {"Id": "10.20.1.11"}, "TargetHealth": {"State": "healthy"}}]}
        raise AssertionError((service, operation))

    def mutate_json(self, service, operation, arguments):
        self.mutations.append((service, operation, list(arguments)))
        return {"Activity": {"StatusCode": "InProgress"}}


class B02EksActionTests(unittest.TestCase):
    def request(self, root: Path) -> MODULE.B02EksRequest:
        return MODULE.B02EksRequest(
            "scrum43-b02-eks-fixture", "111111111111", "ap-northeast-2", "dev-eks",
            MODULE.APPROVED_CLUSTER, MODULE.APPROVED_NODE_GROUP, "i-0123456789abcdef0",
            "arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:targetgroup/example/0123456789abcdef",
            root,
        )

    def test_plan_reads_managed_node_without_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            aws = FakeAws()
            result = MODULE.run_action(self.request(root), aws, mode="plan")
            self.assertEqual(result["platform"], "eks-managed-node")
            self.assertFalse(result["mutation"]["performed"])
            self.assertEqual(aws.mutations, [])

    def test_execute_keeps_desired_capacity_and_uses_no_decrement(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            approval = root / "approval.json"
            approval.write_text(json.dumps({"approved": True, "approvedBy": "owner"}), encoding="utf-8")
            aws = FakeAws()
            result = MODULE.run_action(self.request(root), aws, mode="execute", approval_file=approval)
            self.assertTrue(result["mutation"]["performed"])
            self.assertEqual(result["target"]["capacity"], {"minSize": 2, "desiredSize": 2, "maxSize": 4})
            self.assertIn("--no-should-decrement-desired-capacity", aws.mutations[0][2])

    def test_alb_instance_id_is_rejected_for_eks_health(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            aws = FakeAws()
            original = aws.read_json
            def bad_health(service, operation, arguments):
                if service == "elbv2":
                    return {"TargetHealthDescriptions": [{"Target": {"Id": "i-0123456789abcdef0"}, "TargetHealth": {"State": "healthy"}}]}
                return original(service, operation, arguments)
            aws.read_json = bad_health
            with self.assertRaisesRegex(MODULE.B02EksActionError, "Pod IPs"):
                MODULE.run_action(self.request(root), aws, mode="plan")


if __name__ == "__main__":
    unittest.main()
