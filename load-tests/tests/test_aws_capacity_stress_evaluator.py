from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/evaluate-aws-capacity-stress.py"
CONTRACT = ROOT / "load-tests/aws/contracts/slo-v1.1-frozen.json"
SPEC = importlib.util.spec_from_file_location("capacity_stress_evaluator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def utc(seconds: int) -> str:
    start = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)
    return (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class CapacityStressEvaluatorTest(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        write_json(root / "metadata.json", {
            "runId": "aws-b01-capacity-fixture",
            "platform": "ec2-asg",
            "profileSha256": "a" * 64,
            "sloVersion": "v1.1-frozen",
            "effectiveInputs": {
                "baseRate": 16,
                "stageMultipliers": [1, 2, 4, 8],
                "stageRates": [16, 32, 64, 128],
            },
        })
        write_json(root / "summary.json", {
            "metrics": {
                "http_req_duration": {"p(95)": 210, "p(99)": 310},
                "http_reqs": {"rate": 128},
                "dropped_iterations": {"count": 0},
                "core_completed_operations_total": {"count": 1000},
                "core_successful_operations_total": {"count": 1000},
                "core_unexpected_errors_total": {"count": 0},
                "core_contract_failures_total": {"count": 0},
            }
        })
        write_json(root / "run-status.json", {
            "k6ContainerOomKilled": False,
            "k6ContainerRestartCount": 0,
        })
        write_json(root / "controller-result.json", {
            "terminalReason": "MAX_CAPACITY_REACHED",
            "capacityStabilitySeconds": 120,
        })
        (root / "runner-stats.jsonl").write_text(
            json.dumps({"docker": {"CPUPerc": "15.0%", "MemPerc": "20.0%"}}) + "\n",
            encoding="utf-8",
        )
        (root / "snapshots.jsonl").write_text(
            "\n".join([
                json.dumps({"ts": utc(0), "stageIndex": 0, "stageMultiplier": 1, "logicalCapacity": 2}),
                json.dumps({"ts": utc(120), "stageIndex": 0, "stageMultiplier": 1, "logicalCapacity": 4, "capacityHealthy": True}),
                json.dumps({"ts": utc(121), "stageIndex": 1, "stageMultiplier": 2, "logicalCapacity": 4, "capacityHealthy": True}),
            ])
            + "\n",
            encoding="utf-8",
        )

    def args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(run_dir=root, slo_contract=CONTRACT, capacity_stability_seconds=120)

    def test_valid_capacity_terminal_is_not_an_slo_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "VALID")
            self.assertEqual(result["terminalReason"], "MAX_CAPACITY_REACHED")
            self.assertEqual(result["bottleneckClass"], "max-capacity")
            self.assertTrue(result["comparisonSafe"])

    def test_runner_bottleneck_invalidates_platform_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            status = json.loads((root / "run-status.json").read_text(encoding="utf-8"))
            status["k6ContainerOomKilled"] = True
            write_json(root / "run-status.json", status)
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "INVALID_RUNNER_BOTTLENECK")
            self.assertFalse(result["comparisonSafe"])

    def test_missing_snapshot_window_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "snapshots.jsonl").unlink()
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "INVALID_METRIC_WINDOW")

    def test_natural_workload_completion_is_not_relabelled_as_hard_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            write_json(root / "controller-result.json", {"terminalReason": "WORKLOAD_COMPLETED"})
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "INVALID_TERMINAL_REASON")


if __name__ == "__main__":
    unittest.main()
