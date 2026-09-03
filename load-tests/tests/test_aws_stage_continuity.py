from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/check-stage-continuity.py"
SPEC = importlib.util.spec_from_file_location("stage_continuity", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


BASE = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)


def stamp(offset: int) -> str:
    return (BASE + timedelta(seconds=offset)).isoformat(timespec="seconds").replace("+00:00", "Z")


def snapshot(offset: int, *, nodes: int = 2, pods: int = 2, uid_suffix: str = "stable", **overrides):
    row = {
        "ts": stamp(offset),
        "requiredObservationsValid": True,
        "observationErrors": [],
        "backendOom": False,
        "backendUnhealthy": False,
        "nodeComputeSaturated": False,
        "nodeSchedulingPressure": False,
        "nodeScaleInProgress": False,
        "caActivityActive": False,
        "albHealthy": True,
        "albSaturated": False,
        "capacityHealthy": True,
        "capacity": {"min": 2, "desired": nodes, "max": 4},
        "nodeCount": nodes,
        "nodeReadyCount": nodes,
        "readyNodeCount": nodes,
        "readyNodes": [{"nodeName": f"node-{index}", "uid": f"node-{uid_suffix}-{index}", "ready": True} for index in range(nodes)],
        "backendPods": {
            "count": pods,
            "readyCount": pods,
            "pendingCount": 0,
            "restartCount": 0,
            "placement": [{
                "podName": f"backend-{index}", "uid": f"pod-{uid_suffix}-{index}",
                "nodeName": f"node-{index % max(nodes, 1)}", "phase": "Running",
                "ready": True, "deletionTimestamp": None,
            } for index in range(pods)],
        },
        "deployment": {"desiredReplicas": pods, "availableReplicas": pods, "readyReplicas": pods, "unavailableReplicas": 0},
        "hpa": {"desiredReplicas": pods, "currentReplicas": pods, "maxReplicas": 13},
        "sloWindowComplete": True,
        "sloBreached": False,
        "runnerValid": True,
        "targetRps": 128,
        "achievedRps": 128,
    }
    row.update(overrides)
    return row


def write_stage(root: Path, rows, windows, *, actual_start: bool = True, status=None, controller=None):
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(json.dumps({
        "rate": 128,
        "actualOperationStartAtUtc": stamp(0) if actual_start else None,
        "effectiveInputs": {"baseRate": 128},
    }) + "\n", encoding="utf-8")
    (root / "snapshots.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    (root / "slo-windows.jsonl").write_text("\n".join(json.dumps(row) for row in windows) + "\n", encoding="utf-8")
    (root / "run-status.json").write_text(json.dumps(status or {"workloadSignalReceived": False}) + "\n", encoding="utf-8")
    (root / "controller-result.json").write_text(json.dumps(controller or {"terminalReason": "STAGE_COMPLETE"}) + "\n", encoding="utf-8")


class StageContinuityTests(unittest.TestCase):
    def test_two_fresh_healthy_windows_allow_handoff_without_extra_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            write_stage(root, [snapshot(0), snapshot(60), snapshot(120)], [
                {"windowId": "w-1", "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "ALLOW")
            self.assertEqual(verdict["reasonCodes"], ["TWO_HEALTHY_WINDOWS", "STABLE_IDENTITY", "FRESH_OBSERVATIONS"])

    def test_capacity_drop_from_four_nodes_to_two_requires_low_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-256"
            write_stage(root, [snapshot(0, nodes=4, pods=6), snapshot(60, nodes=2, pods=2)], [
                {"windowId": "w-1", "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=512, now=BASE.timestamp() + 60)
            self.assertEqual(verdict["decision"], "RESTORE_LOW")
            self.assertIn("CAPACITY_DROPPED", verdict["reasonCodes"])

    def test_same_counts_with_uid_replacement_are_not_warm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            write_stage(root, [snapshot(0, uid_suffix="a"), snapshot(60, uid_suffix="b"), snapshot(120, uid_suffix="b")], [
                {"windowId": "w-1", "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "BLOCK")
            self.assertIn("IDENTITY_CHANGED", verdict["reasonCodes"])

    def test_one_window_or_stale_observation_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            write_stage(root, [snapshot(0), snapshot(60)], [
                {"windowId": "w-1", "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 300)
            self.assertEqual(verdict["decision"], "BLOCK")
            self.assertIn("OBSERVATION_STALE", verdict["reasonCodes"])
            self.assertIn("COMPLETE_WINDOWS_MISSING", verdict["reasonCodes"])

    def test_missing_actual_operation_start_is_restore_not_high_rate_allow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            write_stage(root, [snapshot(0), snapshot(60), snapshot(120)], [
                {"windowId": "w-1", "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ], actual_start=False)
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "RESTORE_LOW")
            self.assertIn("ACTUAL_OPERATION_START_MISSING", verdict["reasonCodes"])

    def test_intentional_adaptive_boundary_signal_allows_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-16"
            write_stage(root, [snapshot(0), snapshot(60), snapshot(120)], [
                {"windowId": "w-1", "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ], status={"workloadSignalReceived": True, "k6ExitCode": 2}, controller={
                "terminalReason": "STAGE_COMPLETE",
                "intentionalStageBoundary": True,
            })
            verdict = MODULE.evaluate(root, next_rate=64, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "ALLOW")
            self.assertNotIn("INTERRUPTED_SEGMENT", verdict["reasonCodes"])

    def test_canonical_slo_window_field_names_allow_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-16"
            write_stage(root, [snapshot(0), snapshot(60), snapshot(120)], [
                {
                    "sloWindowId": "1788400560-1788400620",
                    "sloWindowStartUtc": stamp(0),
                    "sloWindowEndUtc": stamp(60),
                    "sloWindowComplete": True,
                    "sloBreached": False,
                },
                {
                    "sloWindowId": "1788400620-1788400680",
                    "sloWindowStartUtc": stamp(60),
                    "sloWindowEndUtc": stamp(120),
                    "sloWindowComplete": True,
                    "sloBreached": False,
                },
            ])
            verdict = MODULE.evaluate(root, next_rate=64, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "ALLOW")
            self.assertEqual(verdict["windowCount"], 2)

    def test_complete_slo_windows_cover_short_polling_span(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-16"
            write_stage(root, [snapshot(0), snapshot(27), snapshot(54), snapshot(81), snapshot(108)], [
                {
                    "sloWindowId": "w-1",
                    "sloWindowStartUtc": stamp(0),
                    "sloWindowEndUtc": stamp(60),
                    "sloWindowComplete": True,
                    "sloBreached": False,
                },
                {
                    "sloWindowId": "w-2",
                    "sloWindowStartUtc": stamp(60),
                    "sloWindowEndUtc": stamp(120),
                    "sloWindowComplete": True,
                    "sloBreached": False,
                },
            ])
            verdict = MODULE.evaluate(root, next_rate=64, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "ALLOW")
            self.assertNotIn("STABLE_DURATION_SHORT", verdict["reasonCodes"])

    def test_unmarked_workload_signal_still_requires_low_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-16"
            write_stage(root, [snapshot(0), snapshot(60), snapshot(120)], [
                {"windowId": "w-1", "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ], status={"workloadSignalReceived": True})
            verdict = MODULE.evaluate(root, next_rate=64, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "RESTORE_LOW")
            self.assertIn("INTERRUPTED_SEGMENT", verdict["reasonCodes"])

    def test_latest_unhealthy_observation_cannot_be_skipped_for_old_healthy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            rows = [snapshot(0), snapshot(60), snapshot(120, backendUnhealthy=True)]
            write_stage(root, rows, [
                {"windowId": "w-1", "windowStartUtc": stamp(0), "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowStartUtc": stamp(60), "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "BLOCK")
            self.assertIn("HEALTHY_WINDOW_MISSING", verdict["reasonCodes"])

    def test_scale_out_identity_transition_is_allowed_after_two_stable_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            write_stage(root, [
                snapshot(0, nodes=2, pods=2, uid_suffix="before"),
                snapshot(60, nodes=3, pods=3, uid_suffix="after"),
                snapshot(120, nodes=3, pods=3, uid_suffix="after"),
            ], [
                {"windowId": "w-1", "windowStartUtc": stamp(0), "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowStartUtc": stamp(60), "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "ALLOW")
            self.assertNotIn("IDENTITY_CHANGED", verdict["reasonCodes"])

    def test_cumulative_restart_count_with_zero_delta_is_not_a_permanent_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            rows = [snapshot(0), snapshot(60), snapshot(120)]
            for row in rows:
                row["backendPods"]["restartCount"] = 2
                row["backendPods"]["restartDelta"] = 0
            write_stage(root, rows, [
                {"windowId": "w-1", "windowStartUtc": stamp(0), "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowStartUtc": stamp(60), "windowEndUtc": stamp(120), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 120)
            self.assertEqual(verdict["decision"], "ALLOW")

    def test_overlapping_windows_are_not_counted_as_distinct_complete_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rate-128"
            write_stage(root, [snapshot(0), snapshot(60), snapshot(120), snapshot(180)], [
                {"windowId": "w-1", "windowStartUtc": stamp(0), "windowEndUtc": stamp(60), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-overlap", "windowStartUtc": stamp(30), "windowEndUtc": stamp(90), "sloWindowComplete": True, "sloBreached": False},
                {"windowId": "w-2", "windowStartUtc": stamp(90), "windowEndUtc": stamp(150), "sloWindowComplete": True, "sloBreached": False},
            ])
            verdict = MODULE.evaluate(root, next_rate=256, now=BASE.timestamp() + 180)
            self.assertEqual(verdict["decision"], "BLOCK")
            self.assertIn("WINDOW_OVERLAP", verdict["reasonCodes"])


if __name__ == "__main__":
    unittest.main()
