from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts/loadtest/aws/evaluate-aws-recovery.py"
SPEC = importlib.util.spec_from_file_location("evaluate_aws_recovery", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

PROFILE_PATH = Path(__file__).parents[1] / "aws/profiles/ec2-recovery.json"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def event(ts: datetime, name: str) -> dict:
    return {"ts": ts.isoformat().replace("+00:00", "Z"), "event": name, "detail": "fixture", "actor": "test"}


class AwsRecoveryEvaluatorTest(unittest.TestCase):
    def build_run(self, root: Path, *, gaps: set[int] | None = None, runner_bottleneck: bool = False):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        run_id = "aws-recovery-fixture-001"
        freeze = root / "freeze-metadata.json"
        d005 = root / "d005-arrival-rate.json"
        b01_profile = root / "ec2-b01.json"
        b01_profile.write_text('{"profileVersion":"fixture-b01"}\n', encoding="utf-8")
        candidate = root / "baseline-candidate.json"
        candidate.write_text('{"candidate":"fixture"}\n', encoding="utf-8")
        b01_profile_sha = hashlib.sha256(b01_profile.read_bytes()).hexdigest()
        candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
        manifest_inputs = {
            "sourceCommitSha": "a" * 40,
            "b01ProfileSha256": b01_profile_sha,
            "baselineCandidateSha256": candidate_sha,
            "d005RateRecordSha256": "c" * 64,
            "d005ArrivalRate": 1,
        }
        spike_effective = {
            "scenario": "spike",
            "classification": "diagnostic",
            "profileSha256": b01_profile_sha,
            "baselineRate": 1.0,
            "peakRateMultiplier": 2.0,
            "peakRate": 2.0,
            "hold": "1m",
            "preAllocatedVUs": 1,
            "maxVUs": 2,
            "timeUnit": "1s",
        }
        spike_digest = hashlib.sha256(
            json.dumps(spike_effective, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest_inputs["spikeEffectiveConfigSha256"] = spike_digest
        manifest = {
            "schemaVersion": "aws-d006-freeze-input-manifest-v1",
            "runId": "aws-b01-fixture-001",
            "sloVersion": "v1.0-frozen",
            "contract": {
                "path": "load-tests/aws/contracts/slo-v1.0.json",
                "sha256": hashlib.sha256(MODULE.CONTRACT_PATH.read_bytes()).hexdigest(),
            },
            "inputs": manifest_inputs,
            "spike": {
                "classification": "diagnostic",
                "effectiveConfigSha256": spike_digest,
                "effectiveConfig": spike_effective,
            },
            "inputDigest": hashlib.sha256(
                json.dumps(manifest_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        write_json(root / "freeze-input-manifest.json", manifest)
        write_json(freeze, {
            "runId": "aws-b01-fixture-001",
            "sloVersion": "v1.0-frozen",
            "approvedBy": "test",
            "freezeInputManifest": "freeze-input-manifest.json",
            "freezeInputDigest": manifest["inputDigest"],
            "sloContractSha256": manifest["contract"]["sha256"],
        })
        write_json(d005, {
            "runId": "aws-b01-fixture-001",
            "arrivalRate": 1,
            "sourceCommitSha": "a" * 40,
            "profileSha256": b01_profile_sha,
            "baselineCandidateSha256": candidate_sha,
        })
        write_json(root / "metadata.json", {
            "runId": run_id,
            "scenarioId": "AWS-RECOVERY",
            "environment": "dev-runtime",
            "rate": 1,
            "commitSha": "a" * 40,
            "k6Image": "grafana/k6:0.54.0@sha256:" + "b" * 64,
            "profileSha256": hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest(),
        })
        events = [
            event(start + timedelta(seconds=0), "RUN_START"),
            event(start + timedelta(seconds=20), "T0"),
            event(start + timedelta(seconds=40), "T1"),
            event(start + timedelta(seconds=50), "T2"),
            event(start + timedelta(seconds=60), "T3"),
            event(start + timedelta(seconds=70), "T4"),
            event(start + timedelta(seconds=75), "T5"),
            event(start + timedelta(seconds=210), "RUN_END"),
        ]
        (root / "operations.jsonl").write_text(
            "\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8"
        )
        points = []
        for bucket in range(0, 210, 10):
            if bucket in (gaps or set()):
                continue
            point_time = (start + timedelta(seconds=bucket)).isoformat().replace("+00:00", "Z")
            points.extend([
                {"type": "Point", "metric": "core_operation_duration", "data": {"time": point_time, "value": 100}},
                {"type": "Point", "metric": "core_operations_total", "data": {"time": point_time, "value": 10}},
                {"type": "Point", "metric": "core_completed_operations_total", "data": {"time": point_time, "value": 10}},
                {"type": "Point", "metric": "core_successful_operations_total", "data": {"time": point_time, "value": 10}},
                {"type": "Point", "metric": "core_unexpected_errors_total", "data": {"time": point_time, "value": 0}},
                {"type": "Point", "metric": "core_contract_failures_total", "data": {"time": point_time, "value": 0}},
            ])
        (root / "raw.json").write_text("\n".join(json.dumps(point) for point in points) + "\n", encoding="utf-8")
        write_json(root / "summary.json", {"metrics": {"dropped_iterations": {"count": 0}}})
        write_json(root / "run-status.json", {
            "k6ExitCode": 0, "k6ContainerOomKilled": False, "k6ContainerRestartCount": 0,
        })
        (root / "runner-stats.jsonl").write_text(json.dumps({
            "docker": {"CPUPerc": "95.00%" if runner_bottleneck else "1.00%", "MemPerc": "2.00%"},
        }) + "\n", encoding="utf-8")
        required = [
            "core_operations_total", "core_completed_operations_total",
            "core_successful_operations_total", "core_unexpected_errors_total",
            "core_contract_failures_total", "core_operation_duration", "runner_stats",
            "aws_target_health", "aws_asg_activities",
        ]
        write_json(root / "monitoring" / "required-metrics.json", {
            "metrics": {
                name: {"status": "collected", "datapointCount": 1}
                for name in required
            }
        })
        return run_id, freeze, d005, b01_profile, candidate

    def args(self, root: Path, run_id: str, freeze: Path, d005: Path, b01_profile: Path, candidate: Path):
        return type("Args", (), {
            "run_dir": root,
            "run_id": run_id,
            "profile": PROFILE_PATH,
            "b01_profile": b01_profile,
            "freeze_metadata": freeze,
            "d005_rate_file": d005,
            "baseline_candidate": candidate,
            "rate": "1",
            "source_sha": "a" * 40,
            "k6_image": "grafana/k6:0.54.0@sha256:" + "b" * 64,
        })()

    def set_recovery_bucket_metric(self, root: Path, bucket_seconds: int, metric: str, value: int) -> None:
        target_time = (
            datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=bucket_seconds)
        ).isoformat().replace("+00:00", "Z")
        lines = []
        changed = False
        for raw_line in (root / "raw.json").read_text(encoding="utf-8").splitlines():
            point = json.loads(raw_line)
            if (
                point.get("metric") == metric
                and point.get("data", {}).get("time") == target_time
            ):
                point["data"]["value"] = value
                changed = True
            lines.append(json.dumps(point))
        self.assertTrue(changed, f"fixture did not contain {metric} at {target_time}")
        (root / "raw.json").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_contiguous_window_passes_and_records_t6(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            result = MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))
            self.assertEqual(result["status"], "PASSED")
            self.assertEqual(result["T1ToT6Seconds"], 160.0)
            self.assertEqual(result["T4ToT6Seconds"], 130.0)
            self.assertEqual(result["T6"], "2026-01-01T00:03:20.000Z")
            events = [json.loads(line)["event"] for line in (root / "operations.jsonl").read_text().splitlines()]
            self.assertLess(events.index("T6"), events.index("RUN_END"))
            self.assertTrue((root / "recovery-verdict.json").exists())

    def test_existing_verdict_is_never_overwritten_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            args = self.args(root, run_id, freeze, d005, b01_profile, candidate)
            MODULE.evaluate(args)
            verdict_path = root / "recovery-verdict.json"
            before = verdict_path.read_bytes()
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(args)
            self.assertEqual(verdict_path.read_bytes(), before)

    def test_missing_required_metric_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            payload = json.loads((root / "monitoring" / "required-metrics.json").read_text())
            del payload["metrics"]["aws_asg_activities"]
            write_json(root / "monitoring" / "required-metrics.json", payload)
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_t5_mid_bucket_does_not_reuse_pre_t5_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            result = MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))
            # T5=75s is inside the 70-80s bucket; the first eligible bucket
            # is 80s, so the 12-bucket window ends at 200s.
            self.assertEqual(result["T6"], "2026-01-01T00:03:20.000Z")

    def test_recovery_window_after_run_end_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            operations = [json.loads(line) for line in (root / "operations.jsonl").read_text().splitlines()]
            for item in operations:
                if item["event"] == "RUN_END":
                    item["ts"] = "2026-01-01T00:02:30Z"
            (root / "operations.jsonl").write_text(
                "\n".join(json.dumps(item) for item in operations) + "\n", encoding="utf-8"
            )
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_t6_after_run_end_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            operations = [json.loads(line) for line in (root / "operations.jsonl").read_text().splitlines()]
            run_end = operations.pop()
            operations.extend([
                run_end,
                {"ts": "2026-01-01T00:03:20Z", "event": "T6"},
            ])
            (root / "operations.jsonl").write_text(
                "\n".join(json.dumps(item) for item in operations) + "\n", encoding="utf-8"
            )
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_gap_in_recovery_window_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root, gaps={120})
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_single_recovery_bucket_unexpected_error_rate_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root, gaps={200})
            # One 10-second bucket has 10% unexpected errors. The aggregate
            # window rate is still below 1%, so this catches aggregate-only
            # validation regressions.
            self.set_recovery_bucket_metric(root, 80, "core_unexpected_errors_total", 1)
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_single_recovery_bucket_contract_failure_rate_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root, gaps={200})
            self.set_recovery_bucket_metric(root, 80, "core_contract_failures_total", 1)
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_adjacent_physical_event_swaps_are_invalid(self):
        for first, second in (("T1", "T2"), ("T3", "T4")):
            with self.subTest(first=first, second=second), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
                operations = [
                    json.loads(line)
                    for line in (root / "operations.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                indices = [index for index, item in enumerate(operations) if item["event"] in (first, second)]
                self.assertEqual(len(indices), 2)
                operations[indices[0]], operations[indices[1]] = operations[indices[1]], operations[indices[0]]
                (root / "operations.jsonl").write_text(
                    "\n".join(json.dumps(item) for item in operations) + "\n", encoding="utf-8"
                )
                with self.assertRaises(MODULE.RecoveryValidationError):
                    MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_missing_freeze_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            freeze.unlink()
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_freeze_without_b01_run_id_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            write_json(freeze, {"sloVersion": "v1.0-frozen", "approvedBy": "test"})
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_d005_rate_mismatch_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            args = self.args(root, run_id, freeze, d005, b01_profile, candidate)
            args.rate = "2"
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(args)

    def test_runner_bottleneck_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root, runner_bottleneck=True)
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(self.args(root, run_id, freeze, d005, b01_profile, candidate))

    def test_source_and_image_gates_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            args = self.args(root, run_id, freeze, d005, b01_profile, candidate)
            args.source_sha = "c" * 40
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(args)

    def test_slo_failure_is_recorded_separately_from_invalid_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id, freeze, d005, b01_profile, candidate = self.build_run(root)
            for bucket in range(80, 200, 10):
                self.set_recovery_bucket_metric(root, bucket, "core_operation_duration", 1000)
            args = self.args(root, run_id, freeze, d005, b01_profile, candidate)
            with self.assertRaises(MODULE.RecoverySloFailure):
                MODULE.evaluate(args)
            failed = MODULE.write_failure_verdict(args, "FAILED", MODULE.RecoverySloFailure("p95 SLO failed"))
            self.assertEqual(failed["status"], "FAILED")
            self.assertEqual(json.loads((root / "recovery-verdict.json").read_text())["status"], "FAILED")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Leave a gap in every possible post-T5 12-bucket window.  A
            # single gap is not sufficient because the evaluator may legally
            # select a later complete window.
            run_id, freeze, d005, b01_profile, candidate = self.build_run(
                root, gaps=set(range(80, 200, 10))
            )
            args = self.args(root, run_id, freeze, d005, b01_profile, candidate)
            with self.assertRaises(MODULE.RecoveryValidationError):
                MODULE.evaluate(args)
            invalid = MODULE.write_failure_verdict(args, "INVALID_RUN", MODULE.RecoveryValidationError("metric gap"))
            self.assertEqual(invalid["status"], "INVALID_RUN")



class ObservabilityEmptyIsValidTests(unittest.TestCase):
    """Plan 07's empty-is-valid contract: a healthy run has zero error counters.

    k6 Counters emit no Point unless incremented, so core_unexpected_errors_total
    and core_contract_failures_total are structurally zero whenever a recovery
    run is clean. Without this contract the gate can never be satisfied by a
    successful experiment.
    """

    PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    REQUIRED = PROFILE["observability"]["required"]

    def status_file(self, root: Path, overrides: dict | None = None) -> None:
        metrics = {name: {"status": "collected", "datapointCount": 1} for name in self.REQUIRED}
        for name, value in (overrides or {}).items():
            metrics[name] = value
        (root / "monitoring").mkdir(parents=True, exist_ok=True)
        (root / "monitoring" / "required-metrics.json").write_text(
            json.dumps({"metrics": metrics}), encoding="utf-8"
        )

    def test_zero_error_counters_pass_when_declared_empty_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.status_file(root, {
                "core_unexpected_errors_total": {"status": "collected", "datapointCount": 0, "emptyIsValid": True},
                "core_contract_failures_total": {"status": "collected", "datapointCount": 0, "emptyIsValid": True},
            })
            result = MODULE.validate_observability(root, self.PROFILE)
            self.assertEqual(
                result["emptyIsValid"],
                ["core_contract_failures_total", "core_unexpected_errors_total"],
            )

    def test_zero_without_declaration_is_still_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.status_file(root, {
                "core_unexpected_errors_total": {"status": "collected", "datapointCount": 0},
            })
            with self.assertRaisesRegex(MODULE.RecoveryValidationError, "core_unexpected_errors_total:empty"):
                MODULE.validate_observability(root, self.PROFILE)

    def test_throughput_metric_cannot_be_waived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.status_file(root, {
                "core_operations_total": {"status": "collected", "datapointCount": 0, "emptyIsValid": True},
            })
            with self.assertRaisesRegex(MODULE.RecoveryValidationError, "core_operations_total:empty"):
                MODULE.validate_observability(root, self.PROFILE)

    def test_missing_and_uncollected_metrics_still_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.status_file(root, {
                "core_unexpected_errors_total": {"status": "pending", "datapointCount": 0, "emptyIsValid": True},
            })
            with self.assertRaisesRegex(MODULE.RecoveryValidationError, "status=pending"):
                MODULE.validate_observability(root, self.PROFILE)
            payload = json.loads((root / "monitoring" / "required-metrics.json").read_text())
            del payload["metrics"]["aws_asg_activities"]
            (root / "monitoring" / "required-metrics.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.RecoveryValidationError, "aws_asg_activities:missing"):
                MODULE.validate_observability(root, self.PROFILE)



class RawAbsenceForEmptyCountersTests(unittest.TestCase):
    """A clean run has no raw Points for the error counters at all.

    load_points() only materialises a counter when k6 emitted at least one
    Point, so evaluate() must accept the absence of a declared empty-is-valid
    counter - but only when the k6 summary corroborates a zero count.
    """

    def build(self, root: Path, *, summary_counts: dict):
        run_id, freeze, d005, b01_profile, candidate = AwsRecoveryEvaluatorTest().build_run(root)
        summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        summary.setdefault("metrics", {})
        for name, value in summary_counts.items():
            summary["metrics"][name] = value
        (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        required = json.loads((root / "monitoring" / "required-metrics.json").read_text(encoding="utf-8"))
        for name in ("core_unexpected_errors_total", "core_contract_failures_total"):
            required["metrics"][name] = {"status": "collected", "datapointCount": 0, "emptyIsValid": True}
        (root / "monitoring" / "required-metrics.json").write_text(json.dumps(required), encoding="utf-8")
        raw_lines = [
            line for line in (root / "raw.json").read_text(encoding="utf-8").splitlines()
            if '"core_unexpected_errors_total"' not in line
            and '"core_contract_failures_total"' not in line
        ]
        (root / "raw.json").write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
        return run_id, freeze, d005, b01_profile, candidate

    def test_absent_counters_accepted_when_summary_reports_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args_source = AwsRecoveryEvaluatorTest()
            run_id, freeze, d005, b01_profile, candidate = self.build(root, summary_counts={
                "core_unexpected_errors_total": {"count": 0},
                "core_contract_failures_total": {"count": 0},
            })
            result = MODULE.evaluate(args_source.args(root, run_id, freeze, d005, b01_profile, candidate))
            self.assertEqual(result["status"], "PASSED")
            self.assertEqual(
                result["observability"]["absentFromRawButSummaryZero"],
                ["core_contract_failures_total", "core_unexpected_errors_total"],
            )

    def test_absent_counter_with_nonzero_summary_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args_source = AwsRecoveryEvaluatorTest()
            run_id, freeze, d005, b01_profile, candidate = self.build(root, summary_counts={
                "core_unexpected_errors_total": {"count": 7},
                "core_contract_failures_total": {"count": 0},
            })
            with self.assertRaisesRegex(MODULE.RecoveryValidationError, "core_unexpected_errors_total"):
                MODULE.evaluate(args_source.args(root, run_id, freeze, d005, b01_profile, candidate))


if __name__ == "__main__":
    unittest.main()
