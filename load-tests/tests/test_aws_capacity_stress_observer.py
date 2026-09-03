from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/observe-aws-capacity-stress.py"
SPEC = importlib.util.spec_from_file_location("capacity_stress_observer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ObserverContractTests(unittest.TestCase):
    def test_aws_port_rejects_every_mutation_operation(self):
        aws = MODULE.AwsReadOnly(region="ap-northeast-2", profile="kdt-travel-admin")
        with self.assertRaisesRegex(MODULE.ObserverError, "non-read"):
            aws.call("autoscaling", "set-desired-capacity", [])

    def test_read_allowlist_contains_only_describe_and_metric_reads(self):
        self.assertTrue(MODULE.READ_OPERATIONS)
        self.assertTrue(all(op.startswith("describe-") or op == "get-metric-statistics" for op in MODULE.READ_OPERATIONS))

    def test_targeted_ssm_port_is_limited_to_marker_observation_operations(self):
        aws = MODULE.AwsReadOnly(region="ap-northeast-2", profile="kdt-travel-admin")
        with self.assertRaisesRegex(MODULE.ObserverError, "non-observation"):
            aws.call_targeted_ssm("delete-command", [])

    def test_alb_target_health_fallback_uses_read_only_bastion_command(self):
        class FakeAws:
            def call_targeted_ssm(self, operation, arguments):
                if operation == "send-command":
                    self.sent_arguments = arguments
                    return {"Command": {"CommandId": "cmd-read-only"}}
                self.assertEqual(operation, "get-command-invocation")
                return {
                    "Status": "Success",
                    "StandardOutputContent": json.dumps({
                        "TargetHealthDescriptions": [{
                            "Target": {"Id": "10.0.0.8"},
                            "TargetHealth": {"State": "healthy"},
                        }]
                    }),
                }

            def assertEqual(self, left, right):
                if left != right:
                    raise AssertionError((left, right))

        fake = FakeAws()
        payload = MODULE.target_health_via_bastion(
            aws=fake,
            bastion_id="i-0123456789abcdef0",
            target_group_arn="arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:targetgroup/backend/0123456789abcdef",
            region="ap-northeast-2",
        )
        self.assertEqual(payload["TargetHealthDescriptions"][0]["TargetHealth"]["State"], "healthy")
        self.assertIn("--document-name", fake.sent_arguments)
        self.assertIn("AWS-RunShellScript", fake.sent_arguments)

    def test_ec2_capacity_requires_healthy_in_service_members(self):
        desired, healthy, details = MODULE.ec2_capacity({
            "AutoScalingGroups": [{
                "MinSize": 2, "DesiredCapacity": 2, "MaxSize": 4,
                "Instances": [
                    {"LifecycleState": "InService", "HealthStatus": "Healthy"},
                    {"LifecycleState": "Pending", "HealthStatus": "Healthy"},
                ],
            }]
        })
        self.assertEqual(desired, 2)
        self.assertFalse(healthy)
        self.assertEqual(details["healthyMembers"], 1)

    def test_sample_snapshot_is_sanitized_and_uses_current_timestamp(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = root / "fixture.json"
            fixture.write_text(json.dumps({"platform": "ec2", "logicalCapacity": 4}), encoding="utf-8")
            args = argparse.Namespace(
                sample_json=fixture,
                platform="ec2",
                asg_name="",
                cluster_name="",
                node_group_name="",
                rds_instance_id="",
                redis_cluster_id="",
                runner_stats_file=None,
                slo_window_file=None,
            )
            snapshot = MODULE.collect_snapshot(args, object())
            self.assertEqual(snapshot["platform"], "ec2")
            self.assertEqual(snapshot["logicalCapacity"], 4)
            self.assertRegex(snapshot["ts"], r"Z$")

    def test_cloudwatch_read_failure_keeps_capacity_snapshot_and_records_limitation(self):
        class FakeAws:
            def call(self, service, operation, arguments):
                if service == "autoscaling":
                    return {
                        "AutoScalingGroups": [{
                            "MinSize": 2,
                            "DesiredCapacity": 2,
                            "MaxSize": 4,
                            "Instances": [
                                {"LifecycleState": "InService", "HealthStatus": "Healthy"},
                                {"LifecycleState": "InService", "HealthStatus": "Healthy"},
                            ],
                        }]
                    }
                raise MODULE.ObserverError("simulated CloudWatch permission denial")

        args = argparse.Namespace(
            sample_json=None,
            platform="ec2",
            asg_name="kdt-travelplanner-dev-backend",
            cluster_name="",
            node_group_name="",
            rds_instance_id="",
            redis_cluster_id="",
            t3_instance_ids=[],
            runner_stats_file=None,
            slo_window_file=None,
        )
        snapshot = MODULE.collect_snapshot(args, FakeAws())
        self.assertEqual(snapshot["logicalCapacity"], 2)
        self.assertTrue(snapshot["capacityHealthy"])
        self.assertEqual(snapshot["backendCpuPercent"], None)
        self.assertEqual(snapshot["sources"][-1], "cloudwatch-unavailable")
        self.assertIn("AWS/EC2:CPUUtilization:read-failed", snapshot["observationErrors"])

    def test_stage_fields_follow_metadata_schedule(self):
        metadata = {
            "startedAtUtc": "2026-08-27T12:54:00Z",
            "effectiveInputs": {
                "baseRate": 16,
                "stageMultipliers": [1, 2, 4, 8],
                "stageDurations": ["5m", "8m", "8m", "8m"],
            },
        }
        early = MODULE.stage_fields(metadata, MODULE.datetime.fromisoformat("2026-08-27T12:55:00+00:00"))
        late = MODULE.stage_fields(metadata, MODULE.datetime.fromisoformat("2026-08-27T13:16:00+00:00"))
        self.assertEqual(early["stageIndex"], 0)
        self.assertEqual(early["stageMultiplier"], 1)
        self.assertEqual(early["targetRate"], 16.0)
        self.assertEqual(late["stageIndex"], 3)
        self.assertEqual(late["stageMultiplier"], 8)
        self.assertEqual(late["targetRate"], 128.0)

    def test_eks_required_observations_fail_closed_when_pending_or_node_state_is_missing(self):
        complete = {
            "hpa": {},
            "deployment": {},
            "backendPods": {"pendingReasons": []},
            "nodeCount": 2,
            "nodeReadyCount": 2,
            "alb": {"healthyTargetCount": 2},
        }
        self.assertEqual(MODULE.required_eks_observations(complete)["status"], "complete")
        incomplete = dict(complete)
        incomplete.pop("alb")
        self.assertEqual(MODULE.required_eks_observations(incomplete)["status"], "missing")

    def test_eks_sample_preserves_pod_and_node_scale_dimensions(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = root / "fixture.json"
            fixture.write_text(json.dumps({
                "platform": "eks",
                "logicalCapacity": 4,
                "nodeScaleOut": True,
                "podScaleOut": True,
                "nodeMaxPending": True,
                "maxCapacityReached": False,
                "requiredObservationsValid": True,
            }), encoding="utf-8")
            args = argparse.Namespace(
                sample_json=fixture,
                platform="eks",
                asg_name="",
                cluster_name="",
                node_group_name="",
                rds_instance_id="",
                redis_cluster_id="",
                t3_instance_ids=[],
                runner_stats_file=None,
                slo_window_file=None,
                snapshot_file=None,
                eks_evidence_file=None,
            )
            snapshot = MODULE.collect_snapshot(args, object())
            self.assertTrue(snapshot["nodeScaleOut"])
            self.assertTrue(snapshot["nodeMaxPending"])
            self.assertTrue(snapshot["requiredObservationsValid"])

    def test_live_eks_refresh_failure_does_not_reuse_static_evidence(self):
        class FakeAws:
            def call(self, service, operation, arguments):
                if service == "eks":
                    return {"nodegroup": {"status": "ACTIVE", "scalingConfig": {"minSize": 2, "desiredSize": 2, "maxSize": 4}}}
                raise MODULE.ObserverError("simulated read failure")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            evidence = root / "eks-evidence.json"
            evidence.write_text(json.dumps({
                "hpa": {}, "backendPods": {"count": 2, "pendingReasons": []},
                "nodeCount": 2, "nodeReadyCount": 2, "alb": {},
            }), encoding="utf-8")
            args = argparse.Namespace(
                sample_json=None,
                platform="eks",
                asg_name="",
                cluster_name="example-dev-eks",
                node_group_name="example-dev-nodes",
                eks_bastion_id="",
                target_group_arn="",
                namespace="travel-planner",
                deployment="backend",
                region="ap-northeast-2",
                rds_instance_id="",
                redis_cluster_id="",
                t3_instance_ids=[],
                runner_stats_file=None,
                slo_window_file=None,
                snapshot_file=None,
                eks_evidence_file=evidence,
            )
            snapshot = MODULE.collect_snapshot(args, FakeAws())
            self.assertFalse(snapshot["requiredObservationsValid"])
            self.assertEqual(snapshot["backendPods"], {})
            self.assertIn("eks:live-refresh-failed", snapshot["observationErrors"])

    def test_stage_pointer_cannot_escape_campaign_run_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            inside = root / "k6" / "rate-64" / "snapshots.jsonl"
            outside = root.parent / "outside.jsonl"
            self.assertEqual(MODULE._safe_pointer_path(root, str(inside)), inside)
            self.assertIsNone(MODULE._safe_pointer_path(root, str(outside)))

    def test_stage_pointer_updates_all_observer_inputs(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            pointer = root / "continuity" / "current-stage.json"
            pointer.parent.mkdir(parents=True)
            paths = {
                "metadataFile": root / "k6/rate-64/metadata.json",
                "runnerStatsFile": root / "k6/rate-64/runner-stats.jsonl",
                "sloWindowFile": root / "k6/rate-64/slo-windows.jsonl",
                "snapshotFile": root / "k6/rate-64/snapshots.jsonl",
            }
            pointer.write_text(json.dumps({key: str(value) for key, value in paths.items()}), encoding="utf-8")
            args = argparse.Namespace(run_dir=root, stage_pointer_file=pointer)
            MODULE.apply_stage_pointer(args)
            self.assertEqual(args.metadata_file, paths["metadataFile"])
            self.assertEqual(args.runner_stats_file, paths["runnerStatsFile"])
            self.assertEqual(args.slo_window_file, paths["sloWindowFile"])
            self.assertEqual(args.snapshot_file, paths["snapshotFile"])


if __name__ == "__main__":
    unittest.main()
