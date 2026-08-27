#!/usr/bin/env python3
"""Evaluate one Capacity/Scale Stress evidence directory.

This evaluator is deliberately separate from the workload runner. It reads
only sanitized run metadata, k6 summaries, runner stats and observer snapshots
and emits a claim-safe result: a missing window is INVALID, a valid SLO miss
is an experimental result, and a Runner bottleneck is never attributed to the
platform.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path


RUNNER_CPU_LIMIT = 90.0
RUNNER_MEMORY_LIMIT = 90.0


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.is_file():
        return {} if default is None else default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {} if default is None else default
    return value if isinstance(value, dict) else ({} if default is None else default)


def read_json_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    values: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def stage_from_metadata(item: dict, metadata: dict) -> dict:
    """Backfill stage labels for snapshots collected before observer repair."""
    if "stageIndex" in item and "stageMultiplier" in item:
        return item
    inputs = metadata.get("effectiveInputs") if isinstance(metadata.get("effectiveInputs"), dict) else {}
    multipliers = inputs.get("stageMultipliers")
    durations = inputs.get("stageDurations")
    started = timestamp(metadata.get("startedAtUtc"))
    if not isinstance(multipliers, list) or not isinstance(durations, list) or len(multipliers) != len(durations) or started is None:
        return item
    seconds = []
    for value in durations:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = float(value)
        elif isinstance(value, str):
            match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh])", value.strip())
            if not match:
                return item
            parsed = float(match.group(1)) * {"s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]
        else:
            return item
        if parsed <= 0:
            return item
        seconds.append(parsed)
    current = timestamp(item.get("ts") or item.get("timestamp"))
    if current is None:
        return item
    elapsed = max(0.0, current - started)
    cursor = 0.0
    selected = len(multipliers) - 1
    for index, duration in enumerate(seconds):
        if elapsed < cursor + duration:
            selected = index
            break
        cursor += duration
    enriched = dict(item)
    enriched["stageIndex"] = selected
    enriched["stageMultiplier"] = multipliers[selected]
    try:
        enriched.setdefault("targetRate", float(inputs.get("baseRate")) * float(multipliers[selected]))
    except (TypeError, ValueError):
        pass
    return enriched


def max_runner_values(path: Path) -> tuple[float | None, float | None, int]:
    cpu: list[float] = []
    memory: list[float] = []
    samples = 0
    pattern = re.compile(r"([0-9]+(?:\.[0-9]+)?)%")
    for entry in read_json_lines(path):
        docker = entry.get("docker")
        if not isinstance(docker, dict):
            continue
        samples += 1
        cpu_match = pattern.search(str(docker.get("CPUPerc", "")))
        mem_match = pattern.search(str(docker.get("MemPerc", "")))
        if cpu_match:
            cpu.append(float(cpu_match.group(1)))
        if mem_match:
            memory.append(float(mem_match.group(1)))
    return (max(cpu) if cpu else None, max(memory) if memory else None, samples)


def summary_metrics(summary: dict) -> dict:
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    def metric(name: str, key: str, default=None):
        value = metrics.get(name)
        return value.get(key, default) if isinstance(value, dict) else default
    return {
        "p95Ms": metric("http_req_duration", "p(95)"),
        "p99Ms": metric("http_req_duration", "p(99)"),
        "achievedRps": metric("http_reqs", "rate"),
        "droppedIterations": metric("dropped_iterations", "count", 0),
        "coreCompleted": metric("core_completed_operations_total", "count", 0),
        "coreSuccessful": metric("core_successful_operations_total", "count", 0),
        "coreUnexpected": metric("core_unexpected_errors_total", "count", 0),
        "coreContractFailures": metric("core_contract_failures_total", "count", 0),
    }


def window_duration(snapshots: list[dict], predicate) -> float:
    active_since: float | None = None
    latest: float | None = None
    longest = 0.0
    for item in snapshots:
        ts = timestamp(item.get("ts") or item.get("timestamp"))
        if ts is None:
            continue
        if predicate(item):
            active_since = ts if active_since is None else active_since
            latest = ts
            longest = max(longest, latest - active_since)
        else:
            active_since = None
            latest = None
    return longest


def derive_slo_breach(item: dict, slo: dict) -> bool:
    if "sloBreached" in item:
        return bool(item["sloBreached"])
    p95 = number(item.get("p95Ms"))
    success = number(item.get("successRate"))
    unexpected = number(item.get("unexpectedErrorRate"))
    contract = number(item.get("contractFailureRate"))
    dropped = number(item.get("droppedIterations"))
    if p95 is None or success is None or unexpected is None or contract is None or dropped is None:
        return False
    return (
        p95 > float(slo.get("p95Ms", 500))
        or success < float(slo.get("successRate", 0.99))
        or unexpected >= float(slo.get("unexpectedErrorRate", 0.01))
        or contract >= float(slo.get("contractFailureRate", 0.01))
        or dropped != 0
    )


def evaluate(args: argparse.Namespace) -> dict:
    run_dir = args.run_dir.resolve()
    metadata = read_json(run_dir / "metadata.json")
    summary = read_json(run_dir / "summary.json")
    status = read_json(run_dir / "run-status.json")
    controller = read_json(run_dir / "controller-result.json")
    snapshots = sorted(
        read_json_lines(run_dir / "snapshots.jsonl"),
        key=lambda item: timestamp(item.get("ts") or item.get("timestamp")) or 0,
    )
    snapshots = [stage_from_metadata(item, metadata) for item in snapshots]
    slo_contract = read_json(Path(args.slo_contract))
    slo = slo_contract.get("baseline", {}) if slo_contract else {}
    metrics = summary_metrics(summary)
    runner_cpu, runner_memory, runner_samples = max_runner_values(run_dir / "runner-stats.jsonl")
    try:
        restart_count = int(status.get("k6ContainerRestartCount", 0) or 0)
    except (TypeError, ValueError):
        restart_count = 1
    runner_invalid = bool(status.get("k6ContainerOomKilled")) or restart_count > 0
    runner_invalid = runner_invalid or (runner_cpu is not None and runner_cpu >= RUNNER_CPU_LIMIT)
    runner_invalid = runner_invalid or (runner_memory is not None and runner_memory >= RUNNER_MEMORY_LIMIT)
    runner_invalid = runner_invalid or any(bool(item.get("runnerVusExhausted")) for item in snapshots)

    stage_rates = metadata.get("effectiveInputs", {}).get("stageRates", [])
    stage_multipliers = metadata.get("effectiveInputs", {}).get("stageMultipliers", [])
    stage_rows = []
    for index, multiplier in enumerate(stage_multipliers):
        rows = [item for item in snapshots if item.get("stageIndex") == index or item.get("stageMultiplier") == multiplier]
        achieved = [number(item.get("achievedRps")) for item in rows]
        achieved = [value for value in achieved if value is not None]
        capacities = [number(item.get("logicalCapacity")) for item in rows]
        capacities = [value for value in capacities if value is not None]
        stage_rows.append({
            "stageIndex": index,
            "multiplier": multiplier,
            "targetRate": stage_rates[index] if index < len(stage_rates) else None,
            "observedSamples": len(rows),
            "achievedRpsMax": max(achieved) if achieved else None,
            "logicalCapacityMax": max(capacities) if capacities else None,
        })

    capacity_stable = window_duration(
        snapshots,
        lambda item: bool(item.get("logicalCapacityStable"))
        or (bool(item.get("capacityHealthy")) and (number(item.get("logicalCapacity")) or 0) >= 4),
    ) >= args.capacity_stability_seconds
    data_saturated = window_duration(snapshots, lambda item: bool(item.get("dataTierSaturated"))) >= args.capacity_stability_seconds
    slo_window_count = sum(1 for item in snapshots if item.get("sloWindow") and derive_slo_breach(item, slo))
    terminal = controller.get("terminalReason")
    valid_metric_window = bool(snapshots) and all(timestamp(item.get("ts") or item.get("timestamp")) is not None for item in snapshots)
    validity = "VALID"
    invalid_reason = None
    if runner_invalid:
        validity = "INVALID_RUNNER_BOTTLENECK"
        invalid_reason = "Runner threshold/OOM/restart/VU exhaustion observed"
    elif not valid_metric_window:
        validity = "INVALID_METRIC_WINDOW"
        invalid_reason = "No complete sanitized observer snapshot window"
    elif terminal not in {"MAX_CAPACITY_REACHED", "SLO_COLLAPSE", "DATA_TIER_SATURATION", "HARD_CEILING"}:
        validity = "INVALID_TERMINAL_REASON"
        invalid_reason = "Controller did not record a preregistered terminal reason"

    if validity == "VALID":
        if terminal == "MAX_CAPACITY_REACHED" or capacity_stable:
            bottleneck = "max-capacity"
        elif terminal == "DATA_TIER_SATURATION" or data_saturated:
            bottleneck = "data-tier"
        elif terminal == "SLO_COLLAPSE" or slo_window_count >= 2:
            bottleneck = "application-compute"
        elif runner_cpu is not None and runner_cpu >= RUNNER_CPU_LIMIT:
            bottleneck = "runner-invalid"
        elif metrics.get("droppedIterations", 0):
            bottleneck = "credit-limited"
        else:
            bottleneck = "ceiling-without-saturation"
    else:
        bottleneck = "runner-invalid" if runner_invalid else None

    result = {
        "schemaVersion": "capacity-stress-evaluation/v1",
        "runId": metadata.get("runId"),
        "platform": metadata.get("platform"),
        "profileSha256": metadata.get("profileSha256"),
        "sloVersion": metadata.get("sloVersion"),
        "effectiveInputs": metadata.get("effectiveInputs", {}),
        "validity": validity,
        "invalidReason": invalid_reason,
        "terminalReason": terminal,
        "bottleneckClass": bottleneck,
        "metrics": metrics,
        "runner": {
            "samples": runner_samples,
            "maxCpuPercent": runner_cpu,
            "maxMemoryPercent": runner_memory,
            "invalid": runner_invalid,
        },
        "stageCurve": stage_rows,
        "snapshotWindow": {
            "samples": len(snapshots),
            "sloBreachedWindows": slo_window_count,
            "capacityStableSeconds": round(window_duration(snapshots, lambda item: bool(item.get("logicalCapacityStable")) or (bool(item.get("capacityHealthy")) and (number(item.get("logicalCapacity")) or 0) >= 4)), 3),
            "dataSaturatedSeconds": round(window_duration(snapshots, lambda item: bool(item.get("dataTierSaturated"))), 3),
            "scaleInCensored": not any(bool(item.get("scaleInStable")) for item in snapshots),
        },
        "comparisonSafe": validity == "VALID" and not runner_invalid,
    }
    (run_dir / "capacity-stress-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--slo-contract", required=True, type=Path)
    parser.add_argument("--capacity-stability-seconds", type=int, default=120)
    args = parser.parse_args()
    result = evaluate(args)
    print(json.dumps({"validity": result["validity"], "terminalReason": result["terminalReason"], "bottleneckClass": result["bottleneckClass"]}, sort_keys=True))
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
