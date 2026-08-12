from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load(module_name: str, relative_path: str):
    script_path = Path(__file__).parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


VALIDATE = _load("validate_aws_run", "scripts/loadtest/aws/validate-aws-run.py")


def write_phase_dir(
    root: Path,
    name: str,
    *,
    run_start: datetime,
    warmup_seconds: int,
    rate: float | None,
    k6_exit_code: int,
    dropped_iterations: int,
    p95_ms: float,
    completed: int,
    successful: int,
    unexpected: int,
    contract_failures: int,
    oom_killed: bool = False,
    restart_count: int = 0,
    cpu_percent_samples: list[float] | None = None,
) -> Path:
    phase_dir = root / "k6" / name
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "metadata.json").write_text(json.dumps({
        "runId": f"run-{name}", "rate": rate, "warmupSeconds": warmup_seconds,
    }), encoding="utf-8")
    (phase_dir / "run-status.json").write_text(json.dumps({
        "k6ExitCode": k6_exit_code,
        "k6ContainerOomKilled": oom_killed,
        "k6ContainerRestartCount": restart_count,
    }), encoding="utf-8")
    if cpu_percent_samples:
        (phase_dir / "runner-stats.jsonl").write_text(
            "\n".join(
                json.dumps({"ts": after_ts, "docker": {"CPUPerc": f"{value}%", "MemPerc": "10.0%"}})
                for after_ts, value in zip(
                    [run_start.isoformat().replace("+00:00", "Z")] * len(cpu_percent_samples), cpu_percent_samples,
                )
            ) + "\n",
            encoding="utf-8",
        )
    (phase_dir / "summary.json").write_text(json.dumps({
        "metrics": {"dropped_iterations": {"count": dropped_iterations}},
    }), encoding="utf-8")
    (phase_dir / "operations.jsonl").write_text(
        json.dumps({"ts": run_start.isoformat().replace("+00:00", "Z"), "event": "RUN_START", "detail": ""}) + "\n",
        encoding="utf-8",
    )

    points = []
    warmup_end = run_start + timedelta(seconds=warmup_seconds)
    during_warmup_time = (run_start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    after_warmup_time = (warmup_end + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")

    def counter_points(metric: str, value_after: int, count_at: str):
        return [{"type": "Point", "metric": metric, "data": {"time": count_at, "value": value_after}}]

    # A decoy count during warm-up that should be excluded once warmup_seconds > 0.
    if warmup_seconds > 0:
        points += counter_points("core_completed_operations_total", 9999, during_warmup_time)
        points += counter_points("core_successful_operations_total", 9999, during_warmup_time)

    for _ in range(completed):
        points += counter_points("core_completed_operations_total", 1, after_warmup_time)
    for _ in range(successful):
        points += counter_points("core_successful_operations_total", 1, after_warmup_time)
    for _ in range(unexpected):
        points += counter_points("core_unexpected_errors_total", 1, after_warmup_time)
    for _ in range(contract_failures):
        points += counter_points("core_contract_failures_total", 1, after_warmup_time)
    points.append({"type": "Point", "metric": "http_req_duration", "data": {"time": after_warmup_time, "value": p95_ms}})
    (phase_dir / "raw.json").write_text("\n".join(json.dumps(point) for point in points) + "\n", encoding="utf-8")
    return phase_dir


def write_valid_fixture_bundle(root: Path, *, run_id: str = "run-valid") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "metadata.json").write_text(json.dumps({"runId": run_id}), encoding="utf-8")
    (root / "operations.jsonl").write_text(
        json.dumps({"ts": "2026-01-01T00:00:00Z", "event": "RUN_START"}) + "\n"
        + json.dumps({"ts": "2026-01-01T01:00:00Z", "event": "RUN_END"}) + "\n",
        encoding="utf-8",
    )
    (root / "evidence-safety.json").write_text(json.dumps({"safe": True, "findingCount": 0}), encoding="utf-8")
    stages = root / "stages"
    fixtures = root / "fixtures"
    stages.mkdir()
    fixtures.mkdir()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for phase in VALIDATE.ASSESSED_PHASES:
        write_phase_dir(
            root, phase, run_start=start, warmup_seconds=0 if phase == "smoke" else 180,
            rate=None if phase == "smoke" else 12, k6_exit_code=0, dropped_iterations=0,
            p95_ms=100, completed=10, successful=10, unexpected=0, contract_failures=0,
        )
        (stages / f"{phase}.json").write_text(json.dumps({
            "stage": phase,
            "runId": run_id,
            "fixtureId": phase,
            "fixtureResultPath": f"fixtures/{phase}.json",
            "fixtureExpectedUsers": 2,
        }), encoding="utf-8")
        (fixtures / f"{phase}.json").write_text(json.dumps({
            "runId": run_id,
            "fixtureId": phase,
            "expected": {"users": 2, "planners": 2, "timelineItems": 6, "timelineItemsPerPlanner": 3},
            "actual": {
                "users": 2,
                "planners": 2,
                "timelineItems": 6,
                "minimumTimelineItemsPerPlanner": 3,
                "maximumTimelineItemsPerPlanner": 3,
            },
        }), encoding="utf-8")
    return root


class HelpersTest(unittest.TestCase):
    def test_timestamp_accepts_k6_nanosecond_precision(self):
        parsed = VALIDATE.timestamp("2026-01-01T00:00:00.123456789Z")
        expected = datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc).timestamp()
        self.assertAlmostEqual(parsed, expected, places=6)

    def test_percentile_of_single_value(self):
        self.assertEqual(VALIDATE.percentile([42.0], 0.95), 42.0)

    def test_percentile_of_empty_list_is_none(self):
        self.assertIsNone(VALIDATE.percentile([], 0.95))


class EvaluatePhaseTest(unittest.TestCase):
    def test_baseline_excludes_warmup_points_from_core_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            phase_dir = write_phase_dir(
                root, "baseline-1", run_start=start, warmup_seconds=180, rate=12,
                k6_exit_code=0, dropped_iterations=0, p95_ms=120,
                completed=1000, successful=995, unexpected=1, contract_failures=0,
            )
            result = VALIDATE.evaluate_phase(phase_dir)

            self.assertTrue(result["excludedWarmupFromCoreCounts"])
            self.assertEqual(result["coreCounts"]["core_completed_operations_total"], 1000)
            self.assertEqual(result["coreCounts"]["core_successful_operations_total"], 995)
            self.assertAlmostEqual(result["successRate"], 0.995)
            self.assertAlmostEqual(result["unexpectedErrorRate"], 0.001)
            self.assertTrue(result["sloPass"])

    def test_baseline_fails_slo_when_error_rate_too_high(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            phase_dir = write_phase_dir(
                root, "baseline-2", run_start=start, warmup_seconds=180, rate=12,
                k6_exit_code=0, dropped_iterations=0, p95_ms=120,
                completed=100, successful=90, unexpected=10, contract_failures=0,
            )
            result = VALIDATE.evaluate_phase(phase_dir)

            self.assertFalse(result["sloPass"])
            self.assertAlmostEqual(result["unexpectedErrorRate"], 0.10)

    def test_dropped_iterations_fail_slo_even_with_good_ratios(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            phase_dir = write_phase_dir(
                root, "baseline-3", run_start=start, warmup_seconds=180, rate=12,
                k6_exit_code=0, dropped_iterations=3, p95_ms=100,
                completed=100, successful=100, unexpected=0, contract_failures=0,
            )
            result = VALIDATE.evaluate_phase(phase_dir)

            self.assertFalse(result["sloPass"])

    def test_smoke_has_no_warmup_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            phase_dir = write_phase_dir(
                root, "smoke", run_start=start, warmup_seconds=0, rate=None,
                k6_exit_code=0, dropped_iterations=0, p95_ms=80,
                completed=4, successful=4, unexpected=0, contract_failures=0,
            )
            result = VALIDATE.evaluate_phase(phase_dir)

            self.assertFalse(result["excludedWarmupFromCoreCounts"])
            self.assertEqual(result["coreCounts"]["core_completed_operations_total"], 4)


class RunnerBottleneckTest(unittest.TestCase):
    def test_not_suspected_under_normal_load(self):
        stats = {"maxCpuPercent": 40.0, "maxMemoryPercent": 30.0}
        self.assertFalse(VALIDATE.runner_bottleneck_suspected(stats, oom_killed=False, restart_count=0))

    def test_suspected_on_oom_kill(self):
        stats = {"maxCpuPercent": None, "maxMemoryPercent": None}
        self.assertTrue(VALIDATE.runner_bottleneck_suspected(stats, oom_killed=True, restart_count=0))

    def test_suspected_on_restart(self):
        stats = {"maxCpuPercent": None, "maxMemoryPercent": None}
        self.assertTrue(VALIDATE.runner_bottleneck_suspected(stats, oom_killed=False, restart_count=1))

    def test_suspected_on_high_cpu(self):
        stats = {"maxCpuPercent": 95.0, "maxMemoryPercent": 20.0}
        self.assertTrue(VALIDATE.runner_bottleneck_suspected(stats, oom_killed=False, restart_count=0))

    def test_evaluate_phase_fails_slo_when_bottleneck_suspected_even_with_good_ratios(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            phase_dir = write_phase_dir(
                root, "baseline-1", run_start=start, warmup_seconds=180, rate=12,
                k6_exit_code=0, dropped_iterations=0, p95_ms=100,
                completed=1000, successful=999, unexpected=0, contract_failures=0,
                cpu_percent_samples=[95.0, 96.0],
            )
            result = VALIDATE.evaluate_phase(phase_dir)

            self.assertTrue(result["runnerBottleneckSuspected"])
            self.assertFalse(result["sloPass"])

    def test_evaluate_phase_records_oom_and_restart_from_run_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            phase_dir = write_phase_dir(
                root, "smoke", run_start=start, warmup_seconds=0, rate=None,
                k6_exit_code=0, dropped_iterations=0, p95_ms=80,
                completed=4, successful=4, unexpected=0, contract_failures=0,
                oom_killed=True, restart_count=2,
            )
            result = VALIDATE.evaluate_phase(phase_dir)

            self.assertTrue(result["k6ContainerOomKilled"])
            self.assertEqual(result["k6ContainerRestartCount"], 2)
            self.assertTrue(result["runnerBottleneckSuspected"])


class BaselineCandidateTest(unittest.TestCase):
    def _rep(self, *, rate: float, slo_pass: bool) -> dict:
        return {"rate": rate, "sloPass": slo_pass}

    def test_frozen_requires_three_passing_reps_at_the_same_rate(self):
        reps = [self._rep(rate=12, slo_pass=True) for _ in range(3)]
        candidate = VALIDATE.evaluate_baseline_candidate(reps, confirmed_rate=12)
        self.assertTrue(candidate["frozen"])
        self.assertEqual(candidate["repsPassed"], 3)

    def test_not_frozen_if_any_rep_misses_slo(self):
        reps = [self._rep(rate=12, slo_pass=True), self._rep(rate=12, slo_pass=True), self._rep(rate=12, slo_pass=False)]
        candidate = VALIDATE.evaluate_baseline_candidate(reps, confirmed_rate=12)
        self.assertFalse(candidate["frozen"])
        self.assertEqual(candidate["repsPassed"], 2)

    def test_not_frozen_if_fewer_than_three_reps(self):
        reps = [self._rep(rate=12, slo_pass=True), self._rep(rate=12, slo_pass=True)]
        candidate = VALIDATE.evaluate_baseline_candidate(reps, confirmed_rate=12)
        self.assertFalse(candidate["frozen"])

    def test_not_frozen_if_reps_disagree_on_rate(self):
        reps = [self._rep(rate=12, slo_pass=True), self._rep(rate=12, slo_pass=True), self._rep(rate=16, slo_pass=True)]
        candidate = VALIDATE.evaluate_baseline_candidate(reps, confirmed_rate=12)
        self.assertFalse(candidate["frozen"])
        self.assertFalse(candidate["rateConsistentAcrossReps"])


class BundleStructureTest(unittest.TestCase):
    def test_missing_operations_jsonl_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({"runId": "r1"}), encoding="utf-8")
            with self.assertRaises(VALIDATE.ValidationError):
                VALIDATE.evaluate_bundle_structure(root, None)

    def test_missing_evidence_safety_without_data_file_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({"runId": "r1"}), encoding="utf-8")
            (root / "operations.jsonl").write_text(
                json.dumps({"ts": "2026-01-01T00:00:00Z", "event": "RUN_START"}) + "\n"
                + json.dumps({"ts": "2026-01-01T00:10:00Z", "event": "RUN_END"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(VALIDATE.ValidationError):
                VALIDATE.evaluate_bundle_structure(root, None)

    def test_reuses_existing_evidence_safety_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({"runId": "r1"}), encoding="utf-8")
            (root / "operations.jsonl").write_text(
                json.dumps({"ts": "2026-01-01T00:00:00Z", "event": "RUN_START"}) + "\n"
                + json.dumps({"ts": "2026-01-01T00:10:00Z", "event": "RUN_END"}) + "\n",
                encoding="utf-8",
            )
            (root / "evidence-safety.json").write_text(json.dumps({"safe": True, "findingCount": 0}), encoding="utf-8")

            result = VALIDATE.evaluate_bundle_structure(root, None)

            self.assertTrue(result["safe"])
            self.assertTrue(result["hasRunBoundaries"])


class FixtureGateTest(unittest.TestCase):
    def assert_fixture_rejected(self, mutate):
        with tempfile.TemporaryDirectory() as directory:
            root = write_valid_fixture_bundle(Path(directory))
            mutate(root)
            report = VALIDATE.evaluate(root, None, confirmed_rate=12)
            self.assertFalse(report["fixtures"]["passed"])
            self.assertFalse(report["passed"])

    def test_valid_fixture_evidence_is_required_and_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            report = VALIDATE.evaluate(write_valid_fixture_bundle(Path(directory)), None, confirmed_rate=12)
            self.assertTrue(report["fixtures"]["passed"])
            self.assertTrue(report["passed"])
            self.assertTrue(all(phase["passed"] for phase in report["fixtures"]["phases"]))
            gate_report = json.loads((Path(directory) / "gate-report.json").read_text(encoding="utf-8"))
            self.assertTrue(gate_report["fixtures"]["passed"])

    def test_missing_fixture_artifact_rejects_gate(self):
        self.assert_fixture_rejected(lambda root: (root / "fixtures" / "spike.json").unlink())

    def test_stale_fixture_run_id_rejects_gate(self):
        def mutate(root):
            path = root / "fixtures" / "ramp.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["runId"] = "run-old"
            path.write_text(json.dumps(payload), encoding="utf-8")

        self.assert_fixture_rejected(mutate)

    def test_swapped_fixture_phase_rejects_gate(self):
        def mutate(root):
            path = root / "fixtures" / "baseline-2.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["fixtureId"] = "baseline-1"
            path.write_text(json.dumps(payload), encoding="utf-8")

        self.assert_fixture_rejected(mutate)

    def test_wrong_fixture_count_rejects_gate(self):
        def mutate(root):
            path = root / "fixtures" / "baseline-1.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["actual"]["timelineItems"] = 7
            path.write_text(json.dumps(payload), encoding="utf-8")

        self.assert_fixture_rejected(mutate)

    def test_wrong_per_planner_count_rejects_gate(self):
        def mutate(root):
            path = root / "fixtures" / "baseline-3.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["actual"]["minimumTimelineItemsPerPlanner"] = 2
            path.write_text(json.dumps(payload), encoding="utf-8")

        self.assert_fixture_rejected(mutate)


if __name__ == "__main__":
    unittest.main()
