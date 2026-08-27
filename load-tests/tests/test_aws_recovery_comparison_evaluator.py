from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/evaluate-aws-recovery-comparison.py"
PROFILE = ROOT / "load-tests/aws/profiles/ec2-eks-recovery-v1.1.json"
CONTRACT = ROOT / "load-tests/aws/contracts/slo-v1.1-candidate.json"
SPEC = importlib.util.spec_from_file_location("comparison_recovery_evaluator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def ts(offset: int) -> str:
    start = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)
    return (start + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


class ComparisonEvaluatorTests(unittest.TestCase):
    def fixture(self, root: Path, *, bad_slo: bool = False, manual: bool = False) -> argparse.Namespace:
        run_id = "scrum43-r03-eks-evaluator" if manual else "scrum43-b02-ec2-evaluator"
        scenario = "R-03" if manual else "B-02"
        profile_sha = hashlib.sha256(PROFILE.read_bytes()).hexdigest()
        contract_sha = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
        write_json(root / "metadata.json", {
            "runId": run_id, "scenarioId": "AWS-RECOVERY-COMPARISON", "platform": "eks" if manual else "ec2",
            "environment": "dev-eks" if manual else "dev-runtime", "profileSha256": profile_sha,
            "sloVersion": "v1.1-candidate", "sloContractSha256": contract_sha,
            "sourceCommitSha": "a" * 40, "k6Image": "grafana/k6:0.54.0@sha256:" + "b" * 64, "rate": 16,
        })
        events = [(0, "RUN_START"), (20, "T0"), (40, "T1"), (50, "T2"), (60, "T3"), (70, "T4"), (75, "T5"), (400, "RUN_END")]
        if manual:
            events.insert(7, (80, "OPERATOR_RECOVERY"))
        (root / "operations.jsonl").write_text(
            "\n".join(json.dumps({"ts": ts(offset), "event": name, "actor": "operator" if name == "OPERATOR_RECOVERY" else "test"}) for offset, name in events) + "\n",
            encoding="utf-8",
        )
        points = []
        # baseline: 20..40, then twelve complete post-T5 buckets starting at 80.
        for bucket in range(20, 210, 10):
            p95 = 600 if bad_slo and bucket >= 80 else 100
            for metric, value in (
                ("core_operation_duration", p95), ("core_operations_total", 160),
                ("core_completed_operations_total", 160), ("core_successful_operations_total", 160),
                ("core_unexpected_errors_total", 0), ("core_contract_failures_total", 0),
            ):
                points.append({"type": "Point", "metric": metric, "data": {"time": ts(bucket), "value": value}})
        (root / "raw.json").write_text("\n".join(json.dumps(point) for point in points) + "\n", encoding="utf-8")
        write_json(root / "summary.json", {"metrics": {"dropped_iterations": {"count": 0}}})
        write_json(root / "run-status.json", {"k6ExitCode": 0, "k6ContainerOomKilled": False, "k6ContainerRestartCount": 0})
        (root / "runner-stats.jsonl").write_text(json.dumps({"docker": {"CPUPerc": "10.0%", "MemPerc": "20.0%"}}) + "\n", encoding="utf-8")
        required = json.loads(PROFILE.read_text(encoding="utf-8"))["observability"]["required"]
        write_json(root / "monitoring/required-metrics.json", {"metrics": {name: {"status": "collected", "datapointCount": 1} for name in required}})
        write_json(root / "control/restoration-readback.json", {"status": "verified", "deploymentReady": True})
        return argparse.Namespace(run_dir=root, run_id=run_id, profile=PROFILE, slo_contract=CONTRACT, rate="16", source_sha="a" * 40, k6_image="grafana/k6:0.54.0@sha256:" + "b" * 64, scenario=scenario)

    def test_slo_pass_adds_t6_without_d005_freeze_inputs(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = self.fixture(root)
            result = MODULE.evaluate(args)
            self.assertEqual(result["status"], "PASSED")
            self.assertEqual(result["validity"], "VALID")
            self.assertIn('"event": "T6"', (root / "operations.jsonl").read_text(encoding="utf-8"))

    def test_complete_bad_window_is_valid_experimental_failure_without_t6(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = self.fixture(root, bad_slo=True)
            result = MODULE.evaluate(args)
            self.assertEqual(result["status"], "VALID_EXPERIMENTAL_FAILURE")
            self.assertIsNone(result["T1ToT6Seconds"])
            self.assertNotIn('"event": "T6"', (root / "operations.jsonl").read_text(encoding="utf-8"))

    def test_zero_error_counters_may_be_omitted_from_raw_when_proven_by_summary(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = self.fixture(root)
            points = []
            for line in (root / "raw.json").read_text(encoding="utf-8").splitlines():
                point = json.loads(line)
                if point.get("metric") not in {"core_unexpected_errors_total", "core_contract_failures_total"}:
                    points.append(point)
            (root / "raw.json").write_text(
                "\n".join(json.dumps(point) for point in points) + "\n",
                encoding="utf-8",
            )
            write_json(root / "summary.json", {
                "metrics": {
                    "dropped_iterations": {"count": 0},
                    "core_unexpected_errors_total": {"count": 0},
                    "core_contract_failures_total": {"count": 0},
                },
            })
            required = json.loads((root / "monitoring/required-metrics.json").read_text(encoding="utf-8"))
            for name in ("core_unexpected_errors_total", "core_contract_failures_total"):
                required["metrics"][name] = {"status": "collected", "datapointCount": 0, "emptyIsValid": True}
            (root / "monitoring/required-metrics.json").write_text(json.dumps(required) + "\n", encoding="utf-8")
            result = MODULE.evaluate(args)
            self.assertEqual(result["status"], "PASSED")

    def test_nanosecond_k6_timestamps_are_counted(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = self.fixture(root)
            points = []
            for line in (root / "raw.json").read_text(encoding="utf-8").splitlines():
                point = json.loads(line)
                if point.get("type") == "Point":
                    point["data"]["time"] = point["data"]["time"].replace(
                        "Z", ".123456789Z"
                    )
                points.append(point)
            (root / "raw.json").write_text(
                "\n".join(json.dumps(point) for point in points) + "\n",
                encoding="utf-8",
            )
            result = MODULE.evaluate(args)
            self.assertEqual(result["status"], "PASSED")

    def test_manual_scenario_requires_operator_event(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = self.fixture(root, manual=True)
            lines = [line for line in (root / "operations.jsonl").read_text().splitlines() if "OPERATOR_RECOVERY" not in line]
            (root / "operations.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ComparisonRecoveryError, "operator recovery"):
                MODULE.evaluate(args)


if __name__ == "__main__":
    unittest.main()
