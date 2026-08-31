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


if __name__ == "__main__":
    unittest.main()
