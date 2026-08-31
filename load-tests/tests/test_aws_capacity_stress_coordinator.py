from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/coordinate-aws-capacity-stress.py"
SPEC = importlib.util.spec_from_file_location("capacity_stress_coordinator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def utc(seconds: int) -> str:
    start = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)
    return (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class CapacityStressCoordinatorTest(unittest.TestCase):
    def test_clean_exit_is_hard_ceiling_only_after_registered_schedule(self) -> None:
        args = MODULE.parse_args([
            "--run-dir", "/tmp/scrum43-stress",
            "--complete-schedule-seconds", "100",
            "--hard-time-ceiling-seconds", "120",
            "--poll-seconds", "1",
            "--",
            "echo", "ok",
        ])
        self.assertEqual(args.complete_schedule_seconds, 100)
        self.assertEqual(args.hard_time_ceiling_seconds, 120)

    def test_campaign_stage_is_recorded_for_separate_breakpoint_runs(self) -> None:
        args = MODULE.parse_args([
            "--run-dir", "/tmp/scrum80-node-breakpoint",
            "--campaign-stage", "node-scale-out-breakpoint",
            "--", "echo", "ok",
        ])
        self.assertEqual(args.campaign_stage, "node-scale-out-breakpoint")

    def test_capacity_terminal_requires_the_registered_stability_window(self) -> None:
        snapshots = [
            {"ts": utc(0), "maxCapacityReached": True, "logicalCapacity": 4},
            {"ts": utc(119), "maxCapacityReached": True, "logicalCapacity": 4},
        ]
        self.assertIsNone(MODULE.terminal_reason(snapshots, 120))
        snapshots.append({"ts": utc(120), "maxCapacityReached": True, "logicalCapacity": 4})
        self.assertEqual(MODULE.terminal_reason(snapshots, 120), "MAX_CAPACITY_REACHED")

    def test_slo_terminal_requires_two_sixty_second_windows(self) -> None:
        snapshots = [
            {"ts": utc(0), "sloWindow": True, "sloWindowComplete": True, "sloWindowSeconds": 60, "sloBreached": True},
        ]
        self.assertIsNone(MODULE.terminal_reason(snapshots, 120))
        snapshots.append({"ts": utc(60), "sloWindow": True, "sloWindowComplete": True, "sloWindowSeconds": 60, "sloBreached": True})
        self.assertEqual(MODULE.terminal_reason(snapshots, 120), "SLO_COLLAPSE")

    def test_node_max_pending_is_terminal_only_when_explicitly_observed(self) -> None:
        snapshots = [
            {"ts": utc(0), "logicalCapacity": 4, "capacityAtMax": True},
            {"ts": utc(120), "logicalCapacity": 4, "capacityAtMax": True},
        ]
        self.assertIsNone(MODULE.terminal_reason(snapshots, 120))
        snapshots[0]["nodeMaxPending"] = True
        snapshots[1]["nodeMaxPending"] = True
        self.assertEqual(MODULE.terminal_reason(snapshots, 120), "NODE_MAX_PENDING")

    def test_adaptive_stage_extension_requires_active_scale_transition(self) -> None:
        self.assertFalse(MODULE.extension_allowed([{"hpa": {"desiredReplicas": 2}, "deployment": {"readyReplicas": 2}}]))
        self.assertTrue(MODULE.extension_allowed([{"hpa": {"desiredReplicas": 4}, "deployment": {"readyReplicas": 2}}]))
        self.assertTrue(MODULE.extension_allowed([{"backendPods": {"pendingCount": 1}}]))

    def test_adaptive_terminal_names_are_actual_sut_outcomes(self) -> None:
        snapshots = [
            {"ts": utc(0), "nodeScaleFailed": True},
            {"ts": utc(120), "nodeScaleFailed": True},
        ]
        self.assertEqual(MODULE.terminal_reason(snapshots, 120), "NODE_SCALE_FAILED")

    def test_adaptive_parse_rejects_more_than_one_extension(self) -> None:
        with self.assertRaises(SystemExit):
            MODULE.parse_args([
                "--run-dir", "/tmp/scrum80-adaptive",
                "--adaptive", "--nominal-hold-seconds", "300",
                "--conditional-extension-seconds", "180", "--max-stage-seconds", "700",
                "--", "echo", "ok",
            ])

    def test_coordinator_stops_workload_without_operator_or_aws_actions(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "cancel-refresh",
            "restore-image",
            "terraform destroy",
            "kubectl apply",
            "set-desired-capacity",
        ):
            self.assertNotIn(forbidden, source)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots = root / "snapshots.jsonl"
            snapshots.write_text(
                "\n".join([
                    json.dumps({"ts": utc(0), "maxCapacityReached": True}),
                    json.dumps({"ts": utc(120), "maxCapacityReached": True}),
                ])
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--run-dir",
                    str(root),
                    "--snapshot-file",
                    str(snapshots),
                    "--capacity-stability-seconds",
                    "120",
                    "--poll-seconds",
                    "0.01",
                    "--",
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            controller = json.loads((root / "controller-result.json").read_text(encoding="utf-8"))
            self.assertEqual(controller["terminalReason"], "MAX_CAPACITY_REACHED")
            self.assertFalse(controller["operatorRecoveryAutomated"])
            self.assertFalse(controller["autoscalingDesiredStateWritten"])


if __name__ == "__main__":
    unittest.main()
