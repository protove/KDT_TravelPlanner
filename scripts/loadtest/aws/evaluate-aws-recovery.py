#!/usr/bin/env python3
"""Fail-closed evaluator for an AWS Recovery run.

The evaluator consumes only evidence already written to a run directory. It
does not call AWS, terminate instances, refresh an ASG, or change Terraform.
It recomputes the SLO window from raw k6 Points, requires the D-005 rate and
D-006 freeze metadata, and writes a sanitized ``recovery-verdict.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CORE_COUNTERS = (
    "core_operations_total",
    "core_completed_operations_total",
    "core_successful_operations_total",
    "core_unexpected_errors_total",
    "core_contract_failures_total",
)
REQUIRED_EVENTS = ("RUN_START", "T0", "T1", "T2", "T3", "T4", "T5", "RUN_END")


class RecoveryValidationError(RuntimeError):
    """A structural or safety failure; it is never an SLO pass."""


def timestamp(value: str) -> float:
    match = re.fullmatch(r"(.+\.)(\d+)(Z|[+-]\d{2}:\d{2})", value)
    if match:
        value = f"{match.group(1)}{match.group(2)[:6].ljust(6, '0')}{match.group(3)}"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError) as error:
        raise RecoveryValidationError(f"invalid UTC timestamp: {value}") from error


def iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict:
    if not path.exists():
        raise RecoveryValidationError(f"missing required evidence file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryValidationError(f"invalid JSON in {path}") from error
    if not isinstance(payload, dict):
        raise RecoveryValidationError(f"JSON object expected in {path}")
    return payload


def load_profile(path: Path) -> dict:
    from importlib.util import module_from_spec, spec_from_file_location

    validator_path = Path(__file__).with_name("validate-aws-recovery-profile.py")
    spec = spec_from_file_location("validate_aws_recovery_profile", validator_path)
    if not spec or not spec.loader:
        raise RecoveryValidationError("could not load recovery profile validator")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    profile = module.load_profile(path)
    try:
        module.validate(profile)
    except ValueError as error:
        raise RecoveryValidationError(str(error)) from error
    return profile


def read_d005(
    path: Path,
    *,
    expected_source_sha: str,
    expected_b01_profile_sha: str,
    baseline_candidate: Path,
) -> tuple[float, dict]:
    payload = read_json(path)
    for field in ("runId", "sourceCommitSha", "profileSha256", "baselineCandidateSha256"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise RecoveryValidationError(f"D-005 field is missing: {field}")
    if not re.fullmatch(r"[0-9a-f]{40}", payload["sourceCommitSha"]):
        raise RecoveryValidationError("D-005 sourceCommitSha is invalid")
    if payload["sourceCommitSha"] != expected_source_sha:
        raise RecoveryValidationError("D-005 sourceCommitSha does not match --source-sha")
    if payload["profileSha256"] != expected_b01_profile_sha:
        raise RecoveryValidationError("D-005 profileSha256 does not match the approved B-01 profile")
    if not re.fullmatch(r"[0-9a-f]{64}", payload["baselineCandidateSha256"]):
        raise RecoveryValidationError("D-005 baselineCandidateSha256 is invalid")
    if not baseline_candidate.exists():
        raise RecoveryValidationError(f"baseline candidate file does not exist: {baseline_candidate}")
    candidate_sha = hashlib.sha256(baseline_candidate.read_bytes()).hexdigest()
    if payload["baselineCandidateSha256"] != candidate_sha:
        raise RecoveryValidationError("D-005 baselineCandidateSha256 does not match the approved candidate file")
    value = payload.get("arrivalRate")
    try:
        rate = float(value)
    except (TypeError, ValueError) as error:
        raise RecoveryValidationError(f"D-005 arrivalRate is missing or invalid: {path}") from error
    if not math.isfinite(rate) or rate <= 0:
        raise RecoveryValidationError("D-005 arrivalRate must be positive")
    return rate, payload


def validate_freeze(path: Path) -> dict:
    payload = read_json(path)
    if payload.get("sloVersion") != "v1.0-frozen":
        raise RecoveryValidationError("D-006 freeze metadata must have sloVersion=v1.0-frozen")
    if not isinstance(payload.get("approvedBy"), str) or not payload["approvedBy"].strip():
        raise RecoveryValidationError("D-006 freeze metadata has no approver")
    if not isinstance(payload.get("runId"), str) or not payload["runId"].strip():
        raise RecoveryValidationError("D-006 freeze metadata has no B-01 runId")
    return payload


def read_events(path: Path) -> dict[str, float]:
    if not path.exists():
        raise RecoveryValidationError(f"missing operations.jsonl: {path}")
    events: dict[str, float] = {}
    duplicates: set[str] = set()
    physical_order: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RecoveryValidationError(f"cannot read operations.jsonl: {path}") from error
    for raw_line in lines:
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise RecoveryValidationError("operations.jsonl contains invalid JSON") from error
        event = entry.get("event")
        if event not in set(REQUIRED_EVENTS) | {"T6"}:
            continue
        physical_order.append(event)
        if event in events:
            duplicates.add(event)
            continue
        if not isinstance(entry.get("ts"), str):
            raise RecoveryValidationError(f"event {event} has no timestamp")
        events[event] = timestamp(entry["ts"])
    if duplicates:
        raise RecoveryValidationError(f"duplicate operation events: {','.join(sorted(duplicates))}")
    missing = [event for event in REQUIRED_EVENTS if event not in events]
    if missing:
        raise RecoveryValidationError(f"missing operation events: {','.join(missing)}")
    ordered = [events[event] for event in REQUIRED_EVENTS]
    if ordered != sorted(ordered):
        raise RecoveryValidationError("operation events are not in chronological order")
    expected_physical_order = list(REQUIRED_EVENTS)
    if "T6" in events:
        expected_physical_order.insert(-1, "T6")
    if physical_order != expected_physical_order:
        expected = ",".join(expected_physical_order)
        actual = ",".join(physical_order)
        raise RecoveryValidationError(
            f"operation events are not in the required physical order: expected {expected}; got {actual}"
        )
    if "T6" in events and events["T6"] > events["RUN_END"]:
        raise RecoveryValidationError("T6 occurs after RUN_END")
    if "T6" in events and events["T6"] < events["T5"]:
        raise RecoveryValidationError("T6 occurs before T5")
    return events


def _metric_payload(point: dict) -> tuple[str, float, float] | None:
    if point.get("type") != "Point" or not isinstance(point.get("data"), dict):
        return None
    data = point["data"]
    metric = point.get("metric")
    if not isinstance(metric, str) or not metric:
        return None
    try:
        return metric, timestamp(data["time"]), float(data.get("value", 0))
    except (KeyError, TypeError, ValueError):
        return None


def load_points(path: Path, bucket_seconds: int) -> tuple[dict[int, list[float]], dict[str, dict[int, float]], set[str]]:
    if not path.exists():
        raise RecoveryValidationError(f"missing raw k6 output: {path}")
    durations: defaultdict[int, list[float]] = defaultdict(list)
    counters: dict[str, defaultdict[int, float]] = {
        name: defaultdict(float) for name in CORE_COUNTERS
    }
    counters["dropped_iterations"] = defaultdict(float)
    observed: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RecoveryValidationError(f"cannot read raw k6 output: {path}") from error
    for raw_line in lines:
        try:
            point = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        payload = _metric_payload(point)
        if payload is None:
            continue
        metric, point_ts, value = payload
        observed.add(metric)
        bucket = math.floor(point_ts / bucket_seconds) * bucket_seconds
        if metric == "core_operation_duration":
            durations[bucket].append(value)
        elif metric in counters:
            counters[metric][bucket] += value
    return durations, counters, observed


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return math.inf
    ordered = sorted(values)
    rank = (len(ordered) - 1) * quantile
    lower, upper = math.floor(rank), math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def runner_stats(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "runner-stats.jsonl"
    if not path.exists():
        raise RecoveryValidationError("runner-stats.jsonl is missing")
    samples = 0
    cpu: list[float] = []
    memory: list[float] = []
    suspected = False
    percent_pattern = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?)%\s*")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("runnerBottleneckSuspected") is True:
            suspected = True
        docker = payload.get("docker")
        if not isinstance(docker, dict):
            continue
        samples += 1
        match = percent_pattern.fullmatch(str(docker.get("CPUPerc", "")))
        if match:
            cpu.append(float(match.group(1)))
        match = percent_pattern.fullmatch(str(docker.get("MemPerc", "")))
        if match:
            memory.append(float(match.group(1)))
    if samples == 0:
        raise RecoveryValidationError("runner-stats.jsonl contains no usable samples")
    return {
        "samples": samples,
        "maxCpuPercent": max(cpu) if cpu else None,
        "maxMemoryPercent": max(memory) if memory else None,
        "runnerBottleneckSuspected": suspected,
    }


def validate_status(run_dir: Path) -> tuple[dict, dict]:
    status = read_json(run_dir / "run-status.json")
    summary = read_json(run_dir / "summary.json")
    if status.get("k6ExitCode") != 0:
        raise RecoveryValidationError(f"k6 exit code is not zero: {status.get('k6ExitCode')}")
    if status.get("k6ContainerOomKilled") is True or int(status.get("k6ContainerRestartCount", 0)) > 0:
        raise RecoveryValidationError("k6 runner container was OOM-killed or restarted")
    summary_metrics = summary.get("metrics")
    if not isinstance(summary_metrics, dict):
        raise RecoveryValidationError("summary.metrics is missing")
    dropped = summary_metrics.get("dropped_iterations", {}).get("count")
    if dropped is None:
        raise RecoveryValidationError("summary.metrics.dropped_iterations.count is missing")
    if float(dropped) > 0:
        raise RecoveryValidationError(f"dropped_iterations is non-zero: {dropped}")
    return status, summary


def validate_observability(run_dir: Path, profile: dict) -> dict:
    relative = profile["observability"]["statusPath"]
    payload = read_json(run_dir / relative)
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        normalized = metrics
    elif isinstance(metrics, list):
        normalized = {item.get("name"): item for item in metrics if isinstance(item, dict) and item.get("name")}
    else:
        raise RecoveryValidationError("observability metrics must be an object or list")
    failures: list[str] = []
    for name in profile["observability"]["required"]:
        item = normalized.get(name)
        if not isinstance(item, dict):
            failures.append(f"{name}:missing")
            continue
        if item.get("status") != "collected":
            failures.append(f"{name}:status={item.get('status')}")
            continue
        try:
            count = int(item.get("datapointCount", 0))
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            failures.append(f"{name}:empty")
    if failures:
        raise RecoveryValidationError("required observability evidence invalid: " + ";".join(failures))
    return {"requiredCount": len(profile["observability"]["required"]), "statusPath": relative}


def append_t6(path: Path, event_timestamp: float) -> None:
    entry = json.dumps({
        "ts": iso_timestamp(event_timestamp),
        "event": "T6",
        "detail": "SLO 120-second recovery window satisfied",
        "actor": "evaluator",
    }, ensure_ascii=False) + "\n"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise RecoveryValidationError("operations.jsonl contains invalid JSON") from error
        if payload.get("event") == "RUN_END":
            lines.insert(index, entry)
            path.write_text("".join(lines), encoding="utf-8")
            return
    raise RecoveryValidationError("cannot record T6 before missing RUN_END event")


def _bucket_stats(
    bucket: int,
    durations: dict[int, list[float]],
    counters: dict[str, dict[int, float]],
    bucket_seconds: int,
) -> dict[str, float | int | bool]:
    completed = counters["core_completed_operations_total"].get(bucket, 0.0)
    successful = counters["core_successful_operations_total"].get(bucket, 0.0)
    unexpected = counters["core_unexpected_errors_total"].get(bucket, 0.0)
    contract = counters["core_contract_failures_total"].get(bucket, 0.0)
    duration_values = durations.get(bucket, [])
    return {
        "bucketStartUtc": iso_timestamp(bucket),
        "p95Ms": percentile(duration_values, 0.95),
        "completed": int(completed),
        "successful": int(successful),
        "unexpected": int(unexpected),
        "contractFailures": int(contract),
        "successRps": successful / bucket_seconds,
        "hasDuration": bool(duration_values),
    }


def evaluate(args: argparse.Namespace) -> dict:
    run_dir = args.run_dir
    profile = load_profile(args.profile)
    freeze = validate_freeze(args.freeze_metadata)
    profile_sha = hashlib.sha256(args.profile.read_bytes()).hexdigest()
    b01_profile_sha = hashlib.sha256(args.b01_profile.read_bytes()).hexdigest()
    d005_rate, d005 = read_d005(
        args.d005_rate_file,
        expected_source_sha=args.source_sha,
        expected_b01_profile_sha=b01_profile_sha,
        baseline_candidate=args.baseline_candidate,
    )
    try:
        expected_rate = float(args.rate)
    except (TypeError, ValueError) as error:
        raise RecoveryValidationError("--rate must be positive") from error
    if not math.isfinite(expected_rate) or expected_rate <= 0 or not math.isclose(d005_rate, expected_rate, rel_tol=0, abs_tol=1e-9):
        raise RecoveryValidationError(f"Recovery rate {expected_rate} does not exactly match D-005 rate {d005_rate}")
    if freeze["runId"] != d005["runId"]:
        raise RecoveryValidationError("D-006 freeze runId does not match the D-005 runId")

    metadata = read_json(run_dir / "metadata.json")
    if metadata.get("runId") != args.run_id:
        raise RecoveryValidationError("metadata.runId does not match --run-id")
    if metadata.get("scenarioId") != "AWS-RECOVERY" or metadata.get("environment") != profile["environment"]:
        raise RecoveryValidationError("metadata scenario/environment does not match Recovery profile")
    expected_profile_sha = hashlib.sha256(args.profile.read_bytes()).hexdigest()
    if metadata.get("profileSha256") != expected_profile_sha:
        raise RecoveryValidationError("metadata.profileSha256 does not match Recovery profile")
    if not re.fullmatch(r"[0-9a-f]{40}", str(metadata.get("commitSha", ""))):
        raise RecoveryValidationError("metadata.commitSha is missing or invalid")
    if not re.search(r"@sha256:[0-9a-f]{64}$", str(metadata.get("k6Image", ""))):
        raise RecoveryValidationError("metadata.k6Image is missing or not digest-pinned")
    if metadata.get("commitSha") != args.source_sha:
        raise RecoveryValidationError("metadata.commitSha does not match approved source SHA")
    if metadata.get("k6Image") != args.k6_image:
        raise RecoveryValidationError("metadata.k6Image does not match approved k6 image digest")
    if not math.isclose(float(metadata.get("rate")), expected_rate, rel_tol=0, abs_tol=1e-9):
        raise RecoveryValidationError("metadata.rate does not match D-005 rate")
    events = read_events(run_dir / "operations.jsonl")
    _, summary = validate_status(run_dir)
    runner = runner_stats(run_dir)
    if (
        runner["runnerBottleneckSuspected"]
        or (runner["maxCpuPercent"] is not None and runner["maxCpuPercent"] >= 90)
        or (runner["maxMemoryPercent"] is not None and runner["maxMemoryPercent"] >= 90)
    ):
        raise RecoveryValidationError("runner bottleneck is marked suspected")
    observability = validate_observability(run_dir, profile)

    bucket_seconds = int(profile["recovery"]["bucketSeconds"])
    window_seconds = int(profile["recovery"]["stableWindowSeconds"])
    budget_seconds = int(profile["recovery"]["budgetSeconds"])
    durations, counters, observed = load_points(run_dir / "raw.json", bucket_seconds)
    missing_core = [name for name in CORE_COUNTERS if name not in observed]
    if "core_operation_duration" not in observed:
        missing_core.append("core_operation_duration")
    if missing_core:
        raise RecoveryValidationError("raw k6 metrics missing: " + ",".join(missing_core))

    t0, t1, t4, t5 = events["T0"], events["T1"], events["T4"], events["T5"]
    baseline_buckets = sorted(
        bucket for bucket in durations
        if bucket + bucket_seconds > t0 and bucket < t1
    )
    if not baseline_buckets:
        raise RecoveryValidationError("no normal baseline buckets exist between T0 and T1")
    base_success_rps_values = [
        counters["core_successful_operations_total"].get(bucket, 0.0) / bucket_seconds
        for bucket in baseline_buckets
        if counters["core_completed_operations_total"].get(bucket, 0.0) > 0
    ]
    if not base_success_rps_values or max(base_success_rps_values) <= 0:
        raise RecoveryValidationError("normal baseline contains no successful Core API operations")
    base_success_rps = statistics.median(base_success_rps_values)

    required_buckets = math.ceil(window_seconds / bucket_seconds)
    # T5 may occur in the middle of a bucket. A recovery window cannot reuse
    # samples that started before T5, so begin at the first complete bucket
    # boundary after the event.
    start_bucket = math.ceil(t5 / bucket_seconds) * bucket_seconds
    candidates = []
    available_after_t5 = sorted(bucket for bucket in durations if bucket >= start_bucket)
    for first in available_after_t5:
        window = [first + offset * bucket_seconds for offset in range(required_buckets)]
        if not all(bucket in durations for bucket in window):
            continue
        stats = [_bucket_stats(bucket, durations, counters, bucket_seconds) for bucket in window]
        if any(not item["hasDuration"] or int(item["completed"]) <= 0 for item in stats):
            continue
        completed_total = sum(int(item["completed"]) for item in stats)
        unexpected_total = sum(int(item["unexpected"]) for item in stats)
        contract_total = sum(int(item["contractFailures"]) for item in stats)
        unexpected_rate = unexpected_total / completed_total if completed_total else math.inf
        contract_rate = contract_total / completed_total if completed_total else math.inf
        bucket_rates_pass = all(
            (float(item["unexpected"]) / int(item["completed"])) < float(profile["recovery"]["unexpectedErrorRate"])
            and (float(item["contractFailures"]) / int(item["completed"])) <= float(profile["recovery"]["contractFailureRate"])
            for item in stats
        )
        bucket_pass = all(
            float(item["p95Ms"]) <= float(profile["recovery"]["p95Ms"])
            and float(item["successRps"]) >= float(profile["recovery"]["capacityFloorRatio"]) * base_success_rps
            for item in stats
        )
        if bucket_pass and bucket_rates_pass:
            candidates.append((window[-1] + bucket_seconds, stats, completed_total, unexpected_total, contract_total, unexpected_rate, contract_rate))
            break

    if not candidates:
        raise RecoveryValidationError("no contiguous 120-second T6 SLO window after T5")
    t6, window_stats, completed_total, unexpected_total, contract_total, unexpected_rate, contract_rate = candidates[0]
    if t6 > events["RUN_END"]:
        raise RecoveryValidationError("T6 recovery window ends after RUN_END")
    t1_to_t6 = t6 - t1
    t4_to_t6 = t6 - t4
    if t1_to_t6 > budget_seconds or t4_to_t6 > budget_seconds:
        raise RecoveryValidationError(f"recovery budget exceeded: T1->T6={t1_to_t6:.1f}s T4->T6={t4_to_t6:.1f}s")
    if "T6" in events and abs(events["T6"] - t6) > bucket_seconds:
        raise RecoveryValidationError("existing T6 event does not match evaluated recovery window")
    if "T6" not in events:
        append_t6(run_dir / "operations.jsonl", t6)

    verdict = {
        "status": "PASSED",
        "runId": args.run_id,
        "scenarioId": "AWS-RECOVERY",
        "sloVersion": freeze["sloVersion"],
        "d005ArrivalRate": d005_rate,
        "b01RunId": d005["runId"],
        "b01ProfileSha256": b01_profile_sha,
        "baselineCandidateSha256": d005["baselineCandidateSha256"],
        "baseSuccessfulRpsMedian": round(base_success_rps, 4),
        "capacityFloorRequiredRps": round(float(profile["recovery"]["capacityFloorRatio"]) * base_success_rps, 4),
        "T0": iso_timestamp(t0),
        "T1": iso_timestamp(t1),
        "T2": iso_timestamp(events["T2"]),
        "T3": iso_timestamp(events["T3"]),
        "T4": iso_timestamp(t4),
        "T5": iso_timestamp(t5),
        "T6": iso_timestamp(t6),
        "RUN_END": iso_timestamp(events["RUN_END"]),
        "T1ToT6Seconds": round(t1_to_t6, 3),
        "T4ToT6Seconds": round(t4_to_t6, 3),
        "budgetSeconds": budget_seconds,
        "stableWindowSeconds": window_seconds,
        "windowCoreCompleted": completed_total,
        "windowCoreUnexpectedErrors": unexpected_total,
        "windowCoreContractFailures": contract_total,
        "windowUnexpectedErrorRate": round(unexpected_rate, 6),
        "windowContractFailureRate": round(contract_rate, 6),
        "runnerStats": runner,
        "observability": observability,
        "bucketStats": window_stats,
        "evidence": {"raw": "raw.json", "operations": "operations.jsonl", "status": "run-status.json", "summary": "summary.json"},
    }
    (run_dir / "recovery-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--b01-profile", type=Path, required=True)
    parser.add_argument("--freeze-metadata", type=Path, required=True)
    parser.add_argument("--d005-rate-file", type=Path, required=True)
    parser.add_argument("--baseline-candidate", type=Path, required=True)
    parser.add_argument("--rate", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--k6-image", required=True)
    args = parser.parse_args()
    try:
        result = evaluate(args)
    except (OSError, RecoveryValidationError, ValueError, json.JSONDecodeError) as error:
        print(f"[recovery-verdict] INVALID: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
