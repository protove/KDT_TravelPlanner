from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/actions/b02-one-instance-replacement.py"
SPEC = importlib.util.spec_from_file_location("b02_one_instance_replacement", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


ACCOUNT_ID = "419496180357"
REGION = "ap-northeast-2"
ASG = "kdt-travelplanner-dev-backend"
INSTANCE = "i-08fa8ce46481a9bbc"
TARGET_GROUP = (
    f"arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT_ID}:"
    "targetgroup/kdt-travelplanner-dev-backend/0123456789abcdef"
)


class FakeAws:
    def __init__(self, *, account: str = ACCOUNT_ID, tags: Mapping[str, str] | None = None):
        self.account = account
        self.instance_tags = {
            "Name": ASG,
            "Project": "kdt-travelplanner",
            "aws:autoscaling:groupName": ASG,
            "Environment": "dev",
            "Service": "travel-planner-backend",
        }
        if tags:
            self.instance_tags.update(tags)
        self.read_calls: list[tuple[str, str, tuple[str, ...]]] = []
        self.mutate_calls: list[tuple[str, str, tuple[str, ...]]] = []

    def read_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]:
        self.read_calls.append((service, operation, tuple(arguments)))
        if service == "sts":
            return {"Account": self.account}
        if service == "autoscaling":
            return {
                "AutoScalingGroups": [{
                    "AutoScalingGroupName": ASG,
                    "MinSize": 2,
                    "DesiredCapacity": 2,
                    "MaxSize": 4,
                    "LaunchTemplate": {"LaunchTemplateId": "lt-04ad74bbdf177e865", "Version": "1"},
                    "Tags": [
                        {"Key": "Environment", "Value": "dev"},
                        {"Key": "Service", "Value": "travel-planner-backend"},
                    ],
                    "Instances": [{
                        "InstanceId": INSTANCE,
                        "LifecycleState": "InService",
                        "HealthStatus": "Healthy",
                    }],
                }]
            }
        if service == "ec2":
            return {
                "Reservations": [{
                    "Instances": [{
                        "InstanceId": INSTANCE,
                        "State": {"Name": "running"},
                        "LaunchTemplate": {"LaunchTemplateId": "lt-04ad74bbdf177e865", "Version": "1"},
                        "Tags": [{"Key": key, "Value": value} for key, value in self.instance_tags.items()],
                    }]
                }]
            }
        if service == "elbv2":
            if operation == "describe-target-groups":
                return {"TargetGroups": [{"TargetGroupArn": TARGET_GROUP, "TargetType": "instance"}]}
            return {
                "TargetHealthDescriptions": [{
                    "Target": {"Id": INSTANCE, "Port": 8080},
                    "TargetHealth": {"State": "healthy"},
                }]
            }
        raise AssertionError((service, operation, arguments))

    def mutate_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]:
        self.mutate_calls.append((service, operation, tuple(arguments)))
        return {"Activity": {"ActivityId": "hidden-from-evidence"}}


def request(root: Path, **overrides: Any) -> MODULE.B02Request:
    values = {
        "run_id": "aws-b02-fixture-001",
        "expected_account_id": ACCOUNT_ID,
        "region": REGION,
        "environment": "dev-runtime",
        "asg_name": ASG,
        "instance_id": INSTANCE,
        "target_group_arn": TARGET_GROUP,
        "evidence_root": root,
    }
    values.update(overrides)
    return MODULE.B02Request(**values)


def cli_args(mode: str, root: Path, output: Path, approval: Path | None = None) -> list[str]:
    values = [
        mode,
        "--run-id", "aws-b02-fixture-001",
        "--expected-account-id", ACCOUNT_ID,
        "--region", REGION,
        "--environment", "dev-runtime",
        "--asg-name", ASG,
        "--instance-id", INSTANCE,
        "--target-group-arn", TARGET_GROUP,
        "--evidence-root", str(root),
        "--output", str(output),
    ]
    if approval is not None:
        values.extend(["--approval-file", str(approval)])
    return values


class AwsB02ActionContractTests(unittest.TestCase):
    def test_target_snapshot_is_exact_and_mutation_has_no_decrement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakeAws()
            target = MODULE.read_target_snapshot(request(root), fake)
            self.assertEqual(target.desired_capacity, 2)
            self.assertEqual(target.target_health, "healthy")
            self.assertEqual(target.target_group_suffix, "targetgroup/kdt-travelplanner-dev-backend/0123456789abcdef")
            command = MODULE.mutation_arguments(request(root))
            self.assertIn("--no-should-decrement-desired-capacity", command)
            self.assertNotIn("--should-decrement-desired-capacity", command)

    def test_comparison_b02_run_id_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            MODULE.validate_request(request(Path(directory), run_id="scrum43-b02-fixture-001"))

    def test_plan_is_read_only_and_evidence_excludes_account_and_raw_arn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "b02-plan.json"
            fake = FakeAws()
            self.assertEqual(MODULE.main(cli_args("plan", root, output), aws=fake), 0)
            self.assertEqual(fake.mutate_calls, [])
            evidence = output.read_text(encoding="utf-8")
            self.assertNotIn(ACCOUNT_ID, evidence)
            self.assertNotIn(TARGET_GROUP, evidence)
            payload = json.loads(evidence)
            self.assertEqual(payload["status"], "PLANNED")
            self.assertFalse(payload["mutation"]["allowed"])
            self.assertTrue(payload["restorationInvariants"]["oneInstanceOnly"])
            self.assertEqual(payload["restorationInvariants"]["desiredCapacityMustRemain"], 2)

    def test_execute_requires_bound_approval_and_replays_without_second_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "b02-action.json"
            approval = root / "approval.json"
            approval.write_text(json.dumps({
                "approved": True,
                "scenario": "B-02",
                "runId": "aws-b02-fixture-001",
                "environment": "dev-runtime",
                "region": REGION,
                "asgName": ASG,
                "instanceId": INSTANCE,
                "approvedBy": "owner",
            }) + "\n", encoding="utf-8")
            fake = FakeAws()
            args = cli_args("execute", root, output, approval)
            self.assertEqual(MODULE.main(args, aws=fake), 0)
            self.assertEqual(len(fake.mutate_calls), 1)
            read_count = len(fake.read_calls)
            self.assertEqual(MODULE.main(args, aws=fake), 0)
            self.assertEqual(len(fake.mutate_calls), 1)
            self.assertEqual(len(fake.read_calls), read_count)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["mutation"]["performed"])
            self.assertFalse(payload["mutation"]["shouldDecrementDesiredCapacity"])
            self.assertEqual(payload["restorationInvariants"]["desiredCapacityMutation"], "none")
            self.assertNotIn(ACCOUNT_ID, output.read_text(encoding="utf-8"))

    def test_incomplete_execute_state_blocks_retry_before_aws_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "restoration-state.json"
            state.write_text(json.dumps({"contractVersion": MODULE.CONTRACT_VERSION, "mode": "execute"}) + "\n", encoding="utf-8")
            fake = FakeAws()
            approval = root / "approval.json"
            approval.write_text("{}\n", encoding="utf-8")
            result = MODULE.main(cli_args("execute", root, root / "b02-action.json", approval), aws=fake)
            self.assertEqual(result, 2)
            self.assertEqual(fake.read_calls, [])
            self.assertEqual(fake.mutate_calls, [])

    def test_tampered_execute_replay_is_rejected_before_aws_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "b02-action.json"
            output.write_text(json.dumps({
                "contractVersion": MODULE.CONTRACT_VERSION,
                "scenario": "B-02",
                "mode": "execute",
                "runId": "aws-b02-fixture-001",
                "region": REGION,
                "environment": "dev-runtime",
                "accountValidated": True,
                "status": "EXECUTED",
                "target": {
                    "asgName": ASG,
                    "instanceId": INSTANCE,
                    "targetGroupSuffix": "targetgroup/kdt-travelplanner-dev-backend/0123456789abcdef",
                },
            }) + "\n", encoding="utf-8")
            fake = FakeAws()
            approval = root / "approval.json"
            approval.write_text("{}\n", encoding="utf-8")
            result = MODULE.main(cli_args("execute", root, output, approval), aws=fake)
            self.assertEqual(result, 2)
            self.assertEqual(fake.read_calls, [])
            self.assertEqual(fake.mutate_calls, [])

    def test_approval_evidence_rejects_account_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "b02-action.json"
            approval = root / "approval.json"
            approval.write_text(json.dumps({
                "approved": True,
                "scenario": "B-02",
                "runId": "aws-b02-fixture-001",
                "environment": "dev-runtime",
                "region": REGION,
                "asgName": ASG,
                "instanceId": INSTANCE,
                "approvedBy": ACCOUNT_ID,
            }) + "\n", encoding="utf-8")
            fake = FakeAws()
            self.assertEqual(MODULE.main(cli_args("execute", root, output, approval), aws=fake), 2)
            self.assertEqual(fake.mutate_calls, [])

    def test_unknown_replay_field_is_rejected_without_echoing_tampered_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "b02-action.json"
            approval = root / "approval.json"
            approval.write_text(json.dumps({
                "approved": True,
                "scenario": "B-02",
                "runId": "aws-b02-fixture-001",
                "environment": "dev-runtime",
                "region": REGION,
                "asgName": ASG,
                "instanceId": INSTANCE,
                "approvedBy": "owner",
            }) + "\n", encoding="utf-8")
            fake = FakeAws()
            args = cli_args("execute", root, output, approval)
            self.assertEqual(MODULE.main(args, aws=fake), 0)
            tampered = json.loads(output.read_text(encoding="utf-8"))
            tampered["tamperedLeak"] = ACCOUNT_ID
            output.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
            reads = len(fake.read_calls)
            self.assertEqual(MODULE.main(args, aws=fake), 2)
            self.assertEqual(len(fake.read_calls), reads)
            self.assertEqual(len(fake.mutate_calls), 1)

    def test_prod_or_service_boundary_is_rejected_before_aws_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakeAws(tags={"Environment": "prod"})
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.read_target_snapshot(request(root), fake)
            self.assertEqual(fake.read_calls[:1], [("sts", "get-caller-identity", ("--region", REGION))])
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.validate_request(request(root, environment="prod"))
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.validate_request(request(root, asg_name="kdt-travelplanner-prod-backend"))

    def test_event_hook_is_t0_to_t5_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            operations = root / "operations.jsonl"
            req = request(root)
            first = MODULE.append_event(operations, req, "T0", "target preflight complete")
            second = MODULE.append_event(operations, req, "T0", "target preflight complete")
            self.assertEqual(first, second)
            self.assertEqual(len(operations.read_text(encoding="utf-8").splitlines()), 1)
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.append_event(operations, req, "T0", "different immutable detail")
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.append_event(operations, req, "T6", "too late")
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.append_event(operations, req, "T1", "account 419496180357")
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.append_event(operations, req, "T2", "cannot skip T1")

    def test_target_group_and_asg_names_are_exact_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.validate_request(request(root, asg_name="kdt-travelplanner-dev-backend-copy"))
            with self.assertRaises(MODULE.B02ActionError):
                MODULE.validate_request(request(root, target_group_arn=TARGET_GROUP.replace("kdt-travelplanner-dev-backend", "other")))


if __name__ == "__main__":
    unittest.main()
