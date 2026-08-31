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
V2_CONTRACT = ROOT / "load-tests/aws/contracts/eks-monolith-breakpoint-slo-v2.0.json"
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
                "http_reqs": {"rate": 512},
                "iterations": {"rate": 128},
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
        write_json(root / "mock" / "evidence.json", {
            "validity": "not-required",
            "health": {"ok": True},
            "requests": {"http5xxLines": 0},
            "headroom": {"maxCpuPercent": 1, "maxMemoryPercent": 1},
        })
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

    def test_missing_stage_labels_are_backfilled_from_fixed_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            metadata["startedAtUtc"] = utc(0)
            metadata["effectiveInputs"]["stageDurations"] = ["5m", "8m", "8m", "8m"]
            write_json(root / "metadata.json", metadata)
            snapshots = [json.loads(line) for line in (root / "snapshots.jsonl").read_text().splitlines()]
            for item in snapshots:
                item.pop("stageIndex", None)
                item.pop("stageMultiplier", None)
            (root / "snapshots.jsonl").write_text("\n".join(json.dumps(item) for item in snapshots) + "\n", encoding="utf-8")
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "VALID")
            self.assertEqual(result["stageCurve"][0]["observedSamples"], 3)
            self.assertEqual(result["stageCurve"][1]["observedSamples"], 0)

    def test_iterations_rate_is_used_for_stage_curve_not_http_request_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["metrics"]["achievedRps"], 128)
            self.assertEqual(result["metrics"]["httpRequestRate"], 512)

    def test_node_count_four_alone_does_not_prove_max_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            controller = json.loads((root / "controller-result.json").read_text(encoding="utf-8"))
            controller["terminalReason"] = "PROFILE_COMPLETE"
            write_json(root / "controller-result.json", controller)
            snapshots = [json.loads(line) for line in (root / "snapshots.jsonl").read_text().splitlines()]
            for item in snapshots:
                item["logicalCapacity"] = 4
                item["capacityHealthy"] = True
                item["maxCapacityReached"] = False
            (root / "snapshots.jsonl").write_text("\n".join(json.dumps(item) for item in snapshots) + "\n", encoding="utf-8")
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "VALID")
            self.assertEqual(result["bottleneckClass"], "ceiling-without-saturation")

    def test_required_complete_slo_window_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            metadata["profileVersion"] = "aws-eks-monolith-breakpoint-v1.0"
            metadata["effectiveInputs"]["requiresCompleteSloWindows"] = True
            write_json(root / "metadata.json", metadata)
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "INVALID_METRIC_WINDOW")

    def test_producer_failure_invalidates_a_live_breakpoint_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            metadata["effectiveInputs"]["requiresCompleteSloWindows"] = True
            metadata["effectiveInputs"]["campaignStage"] = "node-scale-out-breakpoint"
            write_json(root / "metadata.json", metadata)
            status = json.loads((root / "run-status.json").read_text(encoding="utf-8"))
            status["sloWindowProducerExitCode"] = 2
            write_json(root / "run-status.json", status)
            result = MODULE.evaluate(self.args(root))
            self.assertEqual(result["validity"], "INVALID_METRIC_WINDOW")
            self.assertEqual(result["campaignStage"], "node-scale-out-breakpoint")

    def adaptive_fixture(self, root: Path, terminal: str = "NODE_MAX_PENDING") -> None:
        write_json(root / "metadata.json", {
            "runId": "aws-eks-adaptive-fixture",
            "platform": "eks",
            "profileVersion": "aws-eks-monolith-breakpoint-v2.0",
            "profileSha256": "b" * 64,
            "sloVersion": "v2.0-breakpoint",
            "effectiveInputs": {
                "campaignStage": "capacity-stress",
                "requiresCompleteSloWindows": True,
                "stageMultipliers": [1],
                "stageRates": [256],
                "stageDurations": ["5m"],
            },
        })
        write_json(root / "summary.json", {"metrics": {
            "http_req_duration": {"p(95)": 210, "p(99)": 310},
            "iterations": {"rate": 256},
            "dropped_iterations": {"count": 0},
            "core_completed_operations_total": {"count": 1000},
            "core_successful_operations_total": {"count": 1000},
            "core_unexpected_errors_total": {"count": 0},
            "core_contract_failures_total": {"count": 0},
        }})
        write_json(root / "run-status.json", {"k6ContainerOomKilled": False, "k6ContainerRestartCount": 0})
        write_json(root / "controller-result.json", {"terminalReason": terminal})
        (root / "runner-stats.jsonl").write_text(json.dumps({"docker": {"CPUPerc": "15.0%", "MemPerc": "20.0%"}}) + "\n", encoding="utf-8")
        (root / "mock-stats.jsonl").write_text(json.dumps({"docker": {"CPUPerc": "12.0%", "MemPerc": "15.0%"}}) + "\n", encoding="utf-8")
        write_json(root / "mock" / "evidence.json", {
            "validity": "VALID",
            "health": {"httpStatus": 200, "ok": True},
            "requests": {"accessLogLines": 100, "errorLogLines": 0, "http5xxLines": 0},
            "container": {"running": True, "oomKilled": False, "restartCount": 0},
            "headroom": {"maxCpuPercent": 12, "maxMemoryPercent": 15, "samples": 1},
        })
        (root / "snapshots.jsonl").write_text("\n".join(json.dumps({
            "ts": utc(offset), "stageIndex": 0, "stageMultiplier": 1,
            "logicalCapacity": 4, "requiredObservationsValid": True,
            "nodeMaxPending": True,
            "sloWindow": True, "sloWindowComplete": True, "sloWindowSeconds": 60,
            "p95Ms": 210, "successRate": 1.0, "unexpectedErrorRate": 0.0,
            "contractFailureRate": 0.0, "droppedIterations": 0, "sloBreached": False,
        }) for offset in (0, 60)) + "\n", encoding="utf-8")

    def test_adaptive_actual_terminal_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.adaptive_fixture(root)
            result = MODULE.evaluate(argparse.Namespace(run_dir=root, slo_contract=V2_CONTRACT, capacity_stability_seconds=120))
            self.assertEqual(result["validity"], "VALID")
            self.assertTrue(result["adaptiveBreakpoint"])
            self.assertEqual(result["bottleneckClass"], "node-max-pending")

    def test_adaptive_stage_boundary_is_not_a_breakpoint_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.adaptive_fixture(root, terminal="STAGE_COMPLETE")
            result = MODULE.evaluate(argparse.Namespace(run_dir=root, slo_contract=V2_CONTRACT, capacity_stability_seconds=120))
            self.assertEqual(result["validity"], "INVALID_TERMINAL_REASON")

    def test_adaptive_missing_mock_evidence_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.adaptive_fixture(root)
            (root / "mock" / "evidence.json").unlink()
            result = MODULE.evaluate(argparse.Namespace(run_dir=root, slo_contract=V2_CONTRACT, capacity_stability_seconds=120))
            self.assertEqual(result["validity"], "INCOMPLETE_MOCK_DEPENDENCY")
            self.assertFalse(result["comparisonSafe"])

    def test_adaptive_mock_5xx_is_incomplete_before_sut_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.adaptive_fixture(root)
            evidence = json.loads((root / "mock" / "evidence.json").read_text(encoding="utf-8"))
            evidence["requests"]["http5xxLines"] = 1
            write_json(root / "mock" / "evidence.json", evidence)
            result = MODULE.evaluate(argparse.Namespace(run_dir=root, slo_contract=V2_CONTRACT, capacity_stability_seconds=120))
            self.assertEqual(result["validity"], "INCOMPLETE_MOCK_DEPENDENCY")
            self.assertEqual(result["mock"]["requests"]["http5xxLines"], 1)


if __name__ == "__main__":
    unittest.main()
