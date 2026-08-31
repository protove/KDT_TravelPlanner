#!/usr/bin/env python3
"""Evaluate one v1.1 EC2-versus-EKS Recovery run.

This evaluator is intentionally independent from the historical v1.0
D-005/D-006 evaluator.  Comparison runs bind the v1.1 profile, the frozen
normal rate and the v1.1 SLO file directly.  A complete post-T5 window that
misses the SLO is a valid experimental failure and is never retried or turned
into a synthetic T6; a passing window may receive an evaluator-owned T6
marker.  The evaluator never performs AWS or Kubernetes actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from slo_contract import load_contract, satisfies
except ImportError:  # pragma: no cover
    from scripts.loadtest.aws.slo_contract import load_contract, satisfies


RUN_ID_PATTERN = re.compile(r"^scrum43-(b02|r01|r03|r05|r07)-[A-Za-z0-9._-]{1,80}$")
SOURCE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}$")
REQUIRED_EVENTS = ("RUN_START", "T0", "T1", "T2", "T3", "T4", "T5", "RUN_END")
MANUAL_SCENARIOS = {"R-03", "R-05", "R-07"}
CORE_COUNTERS = (
    "core_operations_total",
    "core_completed_operations_total",
    "core_successful_operations_total",
    "core_unexpected_errors_total",
    "core_contract_failures_total",
)


class ComparisonRecoveryError(RuntimeError):
    """A structural, safety or evidence error."""


def normalize_scenario(value: str) -> str:
    normalized = str(value).upper().replace("_", "-")
    if normalized in {"B02", "B-02"}:
        return "B-02"
    if normalized in {"R01", "R-01", "R03", "R-03", "R05", "R-05", "R07", "R-07"}:
        return f"R-{normalized[-2:]}"
    raise ComparisonRecoveryError("--scenario is not an approved Recovery scenario")


def timestamp(value: object) -> float:
    if not isinstance(value, str):
        raise ComparisonRecoveryError("UTC timestamp is missing")
    try:
        # k6 emits RFC3339 timestamps with nanosecond precision while the
        # Python 3.9 runtime accepts at most microseconds.  Truncate only the
        # excess fractional precision; the timestamp remains in the same
        # bucket and no event ordering information is discarded.
        normalized = value.replace("Z", "+00:00")
        normalized = re.sub(
            r"(\.\d{6})\d*(?=\+\d{2}:\d{2}$)",
            r"\1",
            normalized,
        )
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError as error:
        raise ComparisonRecoveryError("invalid UTC timestamp") from error


def iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ComparisonRecoveryError(f"missing required evidence file: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonRecoveryError(f"invalid JSON evidence: {path.name}") from error
    if not isinstance(payload, dict):
        raise ComparisonRecoveryError(f"JSON object expected: {path.name}")
    return payload


def read_events(path: Path) -> dict[str, float]:
    if not path.is_file():
        raise ComparisonRecoveryError("operations.jsonl is missing")
    events: dict[str, float] = {}
    physical: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ComparisonRecoveryError("operations.jsonl contains invalid JSON") from error
        event = record.get("event") if isinstance(record, dict) else None
        if event not in set(REQUIRED_EVENTS) | {"T6"}:
            continue
        if event in events:
            raise ComparisonRecoveryError(f"duplicate Recovery event: {event}")
        events[event] = timestamp(record.get("ts"))
        physical.append(event)
    missing = [event for event in REQUIRED_EVENTS if event not in events]
    if missing:
        raise ComparisonRecoveryError("missing Recovery events: " + ",".join(missing))
    expected = list(REQUIRED_EVENTS)
    if "T6" in events:
        expected.insert(-1, "T6")
    if physical != expected:
        raise ComparisonRecoveryError("Recovery events are not in the required physical order")
    ordered = [events[event] for event in physical]
    if any(left >= right for left, right in zip(ordered, ordered[1:])):
        raise ComparisonRecoveryError("Recovery event timestamps are not strictly chronological")
    return events


def read_all_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ComparisonRecoveryError(f"missing evidence file: {path.name}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_points(path: Path, bucket_seconds: int) -> tuple[dict[int, list[float]], dict[str, dict[int, float]], set[str]]:
    if not path.is_file():
        raise ComparisonRecoveryError("raw.json is missing")
    durations: defaultdict[int, list[float]] = defaultdict(list)
    counters: dict[str, defaultdict[int, float]] = {name: defaultdict(float) for name in CORE_COUNTERS}
    observed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            point = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(point, dict) or point.get("type") != "Point" or not isinstance(point.get("data"), dict):
            continue
        metric = point.get("metric")
        if not isinstance(metric, str):
            continue
        data = point["data"]
        try:
            point_time = timestamp(data.get("time"))
            value = float(data.get("value", 0))
        except (TypeError, ValueError, ComparisonRecoveryError):
            continue
        bucket = math.floor(point_time / bucket_seconds) * bucket_seconds
        observed.add(metric)
        if metric == "core_operation_duration":
            durations[bucket].append(value)
        elif metric in counters:
            counters[metric][bucket] += value
    return durations, counters, observed


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return math.inf
    values = sorted(values)
    rank = (len(values) - 1) * quantile
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (rank - low)


def runner_stats(path: Path) -> dict[str, Any]:
    rows = read_all_json_lines(path)
    cpu: list[float] = []
    memory: list[float] = []
    for row in rows:
        docker = row.get("docker")
        if not isinstance(docker, dict):
            continue
        for field, target in (("CPUPerc", cpu), ("MemPerc", memory)):
            match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)%\s*", str(docker.get(field, "")))
            if match:
                target.append(float(match.group(1)))
    if not rows:
        raise ComparisonRecoveryError("runner-stats.jsonl is empty")
    return {
        "samples": len(rows),
        "maxCpuPercent": max(cpu) if cpu else None,
        "maxMemoryPercent": max(memory) if memory else None,
        "runnerBottleneckSuspected": any(row.get("runnerBottleneckSuspected") is True for row in rows),
    }


def _required_observability(run_dir: Path, profile: dict[str, Any]) -> dict[str, Any]:
    status = read_json(run_dir / profile["observability"]["statusPath"])
    raw = status.get("metrics")
    metrics = raw if isinstance(raw, dict) else {
        item.get("name"): item for item in raw if isinstance(item, dict) and item.get("name")
    } if isinstance(raw, list) else None
    if not isinstance(metrics, dict):
        raise ComparisonRecoveryError("observability metrics must be an object or list")
    failures: list[str] = []
    for name in profile["observability"]["required"]:
        item = metrics.get(name)
        if not isinstance(item, dict) or item.get("status") != "collected":
            failures.append(f"{name}:missing")
            continue
        try:
            count = int(item.get("datapointCount", 0))
        except (TypeError, ValueError):
            count = 0
        if count <= 0 and not (name in {"core_unexpected_errors_total", "core_contract_failures_total"} and item.get("emptyIsValid") is True):
            failures.append(f"{name}:empty")
    if failures:
        raise ComparisonRecoveryError("required observability evidence invalid: " + ";".join(failures))
    return {"requiredCount": len(profile["observability"]["required"]), "statusPath": profile["observability"]["statusPath"]}


def _append_t6(path: Path, event_time: float) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    entry = json.dumps({"ts": iso_timestamp(event_time), "event": "T6", "detail": "v1.1 SLO recovery window satisfied", "actor": "evaluator"}, ensure_ascii=False) + "\n"
    for index, line in enumerate(lines):
        try:
            if json.loads(line).get("event") == "RUN_END":
                lines.insert(index, entry)
                path.write_text("".join(lines), encoding="utf-8")
                return
        except json.JSONDecodeError as error:
            raise ComparisonRecoveryError("operations.jsonl contains invalid JSON") from error
    raise ComparisonRecoveryError("RUN_END is required before recording T6")


def _read_platform_recovery(run_dir: Path) -> dict[str, Any]:
    candidates = (run_dir / "control/restoration-readback.json", run_dir / "restoration-readback.json", run_dir / "aws/restoration-state.json")
    for path in candidates:
        if not path.is_file():
            continue
        payload = read_json(path)
        if payload.get("status") in {"verified", "restored"} or payload.get("deploymentReady") is True:
            return {"status": "verified", "source": str(path.relative_to(run_dir))}
    return {"status": "not-observed", "source": None}


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ComparisonRecoveryError(f"{path.name} already exists; refusing overwrite")
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    except FileExistsError as error:
        raise ComparisonRecoveryError(f"{path.name} was created concurrently") from error


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir.resolve()
    verdict_path = run_dir / "recovery-verdict.json"
    if verdict_path.exists():
        raise ComparisonRecoveryError("recovery-verdict.json already exists; refusing overwrite")
    scenario = normalize_scenario(args.scenario)
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ComparisonRecoveryError("--run-id must use scrum43-b02/r01/r03/r05/r07")
    profile = read_json(args.profile)
    if profile.get("sloVersion") not in {"v1.1-candidate", "v1.1-frozen"}:
        raise ComparisonRecoveryError("comparison Recovery profile must use v1.1 candidate/frozen")
    profile_sha = hashlib.sha256(args.profile.read_bytes()).hexdigest()
    contract = load_contract(args.slo_contract)
    contract_slo_version = contract.get("sloVersion")
    if contract_slo_version not in {"v1.1-candidate", "v1.1-frozen"}:
        raise ComparisonRecoveryError("comparison SLO contract must be v1.1 candidate/frozen")
    contract_sha = hashlib.sha256(args.slo_contract.read_bytes()).hexdigest()
    metadata = read_json(run_dir / "metadata.json")
    if metadata.get("runId") != args.run_id or metadata.get("scenarioId") != "AWS-RECOVERY-COMPARISON":
        raise ComparisonRecoveryError("metadata runId/scenarioId does not match comparison Recovery")
    if metadata.get("profileSha256") != profile_sha:
        raise ComparisonRecoveryError("metadata.profileSha256 does not match comparison profile")
    if metadata.get("sloVersion") != contract_slo_version:
        raise ComparisonRecoveryError("metadata.sloVersion does not match the supplied SLO contract")
    if metadata.get("sloContractSha256") != contract_sha:
        raise ComparisonRecoveryError("metadata.sloContractSha256 does not match v1.1 contract")
    if metadata.get("sourceCommitSha") != args.source_sha or not SOURCE_SHA_PATTERN.fullmatch(str(args.source_sha)):
        raise ComparisonRecoveryError("metadata.sourceCommitSha does not match approved source SHA")
    if metadata.get("k6Image") != args.k6_image or not IMAGE_PATTERN.search(str(args.k6_image)):
        raise ComparisonRecoveryError("metadata.k6Image does not match the digest-pinned image")
    try:
        requested_rate = float(args.rate)
        metadata_rate = float(metadata.get("rate"))
    except (TypeError, ValueError) as error:
        raise ComparisonRecoveryError("comparison rate is invalid") from error
    if not math.isfinite(requested_rate) or requested_rate <= 0 or not math.isclose(requested_rate, metadata_rate, rel_tol=0, abs_tol=1e-9):
        raise ComparisonRecoveryError("metadata.rate does not match the frozen comparison rate")

    events = read_events(run_dir / "operations.jsonl")
    if scenario in MANUAL_SCENARIOS:
        operator_lines = read_all_json_lines(run_dir / "operations.jsonl")
        if not any(row.get("event") == "OPERATOR_RECOVERY" and row.get("actor") == "operator" and timestamp(row.get("ts")) >= events["T3"] for row in operator_lines):
            raise ComparisonRecoveryError("manual Recovery scenario has no operator recovery event")
    summary = read_json(run_dir / "summary.json")
    status = read_json(run_dir / "run-status.json")
    if status.get("k6ExitCode") != 0 or status.get("k6ContainerOomKilled") is True or int(status.get("k6ContainerRestartCount", 0) or 0) > 0:
        raise ComparisonRecoveryError("k6 workload status is not clean")
    dropped = summary.get("metrics", {}).get("dropped_iterations", {}).get("count") if isinstance(summary.get("metrics"), dict) else None
    if dropped is None or float(dropped) != 0:
        raise ComparisonRecoveryError("dropped_iterations must be zero")
    runner = runner_stats(run_dir / "runner-stats.jsonl")
    if runner["runnerBottleneckSuspected"] or (runner["maxCpuPercent"] is not None and runner["maxCpuPercent"] >= 90) or (runner["maxMemoryPercent"] is not None and runner["maxMemoryPercent"] >= 90):
        raise ComparisonRecoveryError("runner bottleneck is marked suspected")
    observability = _required_observability(run_dir, profile)

    bucket_seconds = int(contract["recovery"]["bucketSeconds"])
    window_seconds = int(contract["recovery"]["stableWindowSeconds"])
    durations, counters, observed = load_points(run_dir / "raw.json", bucket_seconds)
    # k6's handleSummary output can legitimately omit a zero-valued counter
    # from raw Point records.  Keep the raw-metric contract fail-closed for
    # positive counters, while accepting only the two explicitly empty-valid
    # error counters when summary.json and required-metrics.json both prove a
    # zero count.  This does not synthesize points or change SLO arithmetic.
    required_status = read_json(run_dir / profile["observability"]["statusPath"])
    status_metrics = required_status.get("metrics")
    if isinstance(status_metrics, list):
        status_metrics = {
            item.get("name"): item
            for item in status_metrics
            if isinstance(item, dict) and item.get("name")
        }
    summary_metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    omitted_zero_valid = {
        name
        for name in ("core_unexpected_errors_total", "core_contract_failures_total")
        if isinstance(status_metrics, dict)
        and isinstance(status_metrics.get(name), dict)
        and status_metrics[name].get("emptyIsValid") is True
        and isinstance(summary_metrics.get(name), dict)
        and float(summary_metrics[name].get("count", 0) or 0) == 0
    }
    missing = [
        name
        for name in (*CORE_COUNTERS, "core_operation_duration")
        if name not in observed and name not in omitted_zero_valid
    ]
    if missing:
        raise ComparisonRecoveryError("raw k6 metrics missing: " + ",".join(missing))
    baseline_buckets = sorted(bucket for bucket in durations if durations[bucket] and events["T0"] < bucket + bucket_seconds <= events["T1"])
    base_rates = [counters["core_successful_operations_total"].get(bucket, 0) / bucket_seconds for bucket in baseline_buckets if counters["core_completed_operations_total"].get(bucket, 0) > 0]
    if not base_rates or max(base_rates) <= 0:
        raise ComparisonRecoveryError("normal baseline contains no successful Core API operations")
    base_success_rps = statistics.median(base_rates)
    required_buckets = math.ceil(window_seconds / bucket_seconds)
    first_bucket = math.ceil(events["T5"] / bucket_seconds) * bucket_seconds
    complete_window_seen = False
    passing: tuple[float, list[dict[str, Any]]] | None = None
    failures: list[dict[str, Any]] = []
    for first in sorted(bucket for bucket in durations if bucket >= first_bucket):
        window = [first + index * bucket_seconds for index in range(required_buckets)]
        if not all(bucket in durations for bucket in window):
            continue
        rows: list[dict[str, Any]] = []
        for bucket in window:
            completed = counters["core_completed_operations_total"].get(bucket, 0)
            successful = counters["core_successful_operations_total"].get(bucket, 0)
            unexpected = counters["core_unexpected_errors_total"].get(bucket, 0)
            contract_failures = counters["core_contract_failures_total"].get(bucket, 0)
            if not durations[bucket] or completed <= 0:
                break
            rows.append({
                "bucketStartUtc": iso_timestamp(bucket),
                "p95Ms": percentile(durations[bucket], 0.95),
                "completed": int(completed),
                "successful": int(successful),
                "unexpected": int(unexpected),
                "contractFailures": int(contract_failures),
                "successRps": successful / bucket_seconds,
            })
        if len(rows) != required_buckets:
            continue
        complete_window_seen = True
        checks = []
        for row in rows:
            completed = row["completed"]
            checks.append({
                "p95": satisfies(contract, "p95Ms", float(row["p95Ms"])),
                "capacity": satisfies(contract, "capacityFloorRatio", float(row["successRps"]) / base_success_rps),
                "unexpected": satisfies(contract, "unexpectedErrorRate", float(row["unexpected"]) / completed),
                "contract": satisfies(contract, "recoveryContractFailureRate", float(row["contractFailures"]) / completed),
            })
        if all(all(check.values()) for check in checks):
            passing = (window[-1] + bucket_seconds, rows)
            break
        failures.append({"windowStartUtc": rows[0]["bucketStartUtc"], "checks": checks})

    platform_recovery = _read_platform_recovery(run_dir)
    if passing:
        t6, window_rows = passing
        if t6 > events["RUN_END"]:
            raise ComparisonRecoveryError("T6 recovery window ends after RUN_END")
        if "T6" in events and abs(events["T6"] - t6) > bucket_seconds:
            raise ComparisonRecoveryError("existing T6 does not match the evaluated window")
        if "T6" not in events:
            _append_t6(run_dir / "operations.jsonl", t6)
        result = {
            "status": "PASSED",
            "validity": "VALID",
            "runId": args.run_id,
            "scenarioId": "AWS-RECOVERY-COMPARISON",
            "scenario": scenario,
            "platform": metadata.get("platform"),
            "sloVersion": contract_slo_version,
            "profileSha256": profile_sha,
            "sloContractSha256": contract_sha,
            "rate": requested_rate,
            "T0": iso_timestamp(events["T0"]), "T1": iso_timestamp(events["T1"]), "T2": iso_timestamp(events["T2"]),
            "T3": iso_timestamp(events["T3"]), "T4": iso_timestamp(events["T4"]), "T5": iso_timestamp(events["T5"]),
            "T6": iso_timestamp(t6), "RUN_END": iso_timestamp(events["RUN_END"]),
            "T1ToT6Seconds": round(t6 - events["T1"], 3), "T4ToT6Seconds": round(t6 - events["T4"], 3),
            "recoveryBudgetSeconds": contract["recovery"]["budgetSeconds"],
            "baseSuccessfulRpsMedian": round(base_success_rps, 4),
            "platformRecovery": platform_recovery,
            "runner": runner,
            "observability": observability,
            "windowStats": window_rows,
            "evidence": {"raw": "raw.json", "operations": "operations.jsonl", "summary": "summary.json", "status": "run-status.json"},
        }
    elif complete_window_seen:
        result = {
            "status": "VALID_EXPERIMENTAL_FAILURE",
            "validity": "VALID",
            "runId": args.run_id,
            "scenarioId": "AWS-RECOVERY-COMPARISON",
            "scenario": scenario,
            "platform": metadata.get("platform"),
            "sloVersion": contract_slo_version,
            "profileSha256": profile_sha,
            "sloContractSha256": contract_sha,
            "rate": requested_rate,
            "errorType": "RecoverySloFailure",
            "detail": "complete post-T5 windows were observed but none satisfied the frozen v1.1 SLO",
            "T0": iso_timestamp(events["T0"]), "T1": iso_timestamp(events["T1"]), "T2": iso_timestamp(events["T2"]),
            "T3": iso_timestamp(events["T3"]), "T4": iso_timestamp(events["T4"]), "T5": iso_timestamp(events["T5"]),
            "RUN_END": iso_timestamp(events["RUN_END"]),
            "T1ToT6Seconds": None, "T4ToT6Seconds": None,
            "recoveryBudgetSeconds": contract["recovery"]["budgetSeconds"],
            "baseSuccessfulRpsMedian": round(base_success_rps, 4),
            "platformRecovery": platform_recovery,
            "runner": runner,
            "observability": observability,
            "failedWindows": failures,
            "evidence": {"raw": "raw.json", "operations": "operations.jsonl", "summary": "summary.json", "status": "run-status.json"},
        }
    else:
        raise ComparisonRecoveryError("no complete post-T5 evidence window")
    _write_new(verdict_path, result)
    return result


def failure_verdict(args: argparse.Namespace, error: Exception) -> dict[str, Any]:
    payload = {
        "status": "INVALID_RUN",
        "validity": "INVALID",
        "runId": args.run_id,
        "scenarioId": "AWS-RECOVERY-COMPARISON",
        "sloVersion": "v1.1-frozen",
        "errorType": error.__class__.__name__,
        "detail": str(error).replace("\n", " ")[:240],
        "evidence": {"failureArtifact": "raw.json"},
    }
    _write_new(args.run_dir.resolve() / "recovery-verdict.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--slo-contract", type=Path, required=True)
    parser.add_argument("--rate", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--k6-image", required=True)
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args)
    except (OSError, ComparisonRecoveryError, ValueError, json.JSONDecodeError) as error:
        try:
            result = failure_verdict(args, error)
        except ComparisonRecoveryError as write_error:
            print(f"[comparison-recovery] INVALID_RUN: {write_error}")
            return 2
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
