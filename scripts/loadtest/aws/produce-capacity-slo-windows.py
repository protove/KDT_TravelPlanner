#!/usr/bin/env python3
"""Produce complete, non-overlapping 60-second SLO windows from k6 JSON.

The k6 JSON output is append-only while a run is in progress.  This producer
tails that file and emits a window only after its end timestamp is present in
the stream.  It is deliberately independent from the platform observer: the
observer can join the latest window with fresh EKS evidence without treating
an aggregate summary written after k6 exits as a live SLO signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CORE_COUNTERS = {
    "core_operations_total",
    "core_completed_operations_total",
    "core_successful_operations_total",
    "core_unexpected_errors_total",
    "core_contract_failures_total",
}
ALL_COUNTERS = CORE_COUNTERS | {"dropped_iterations", "iterations"}


class SloWindowError(RuntimeError):
    """Raised when the immutable metadata or contract cannot be used."""


def timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    # k6 may emit nanoseconds; Python's stdlib accepts microseconds at most.
    match = re.fullmatch(r"(.+\.)(\d+)(Z|[+-]\d{2}:\d{2})", value)
    if match:
        value = f"{match.group(1)}{match.group(2)[:6].ljust(6, '0')}{match.group(3)}"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def duration_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh])", value.strip())
    if not match:
        return None
    return float(match.group(1)) * {"s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def read_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SloWindowError(f"metadata is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise SloWindowError("metadata must be a JSON object")
    started = timestamp(payload.get("startedAtUtc"))
    if started is None:
        raise SloWindowError("metadata.startedAtUtc is required")
    return payload


def read_contract(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SloWindowError(f"SLO contract is not valid JSON: {path}") from error
    baseline = payload.get("baseline") if isinstance(payload, dict) else None
    if not isinstance(baseline, dict):
        raise SloWindowError("SLO contract baseline section is missing")
    required = ("p95Ms", "successRate", "unexpectedErrorRate", "contractFailureRate", "droppedIterations")
    if any(key not in baseline for key in required):
        raise SloWindowError("SLO contract baseline comparator is incomplete")
    return payload


def read_points(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    points: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict) or item.get("type") != "Point":
                continue
            data = item.get("data")
            point_ts = timestamp(data.get("time")) if isinstance(data, dict) else None
            if point_ts is None or not isinstance(item.get("metric"), str):
                continue
            try:
                value = float(data.get("value")) if isinstance(data, dict) else None
            except (TypeError, ValueError):
                value = None
            if value is None or not math.isfinite(value):
                continue
            points.append({"metric": item["metric"], "ts": point_ts, "value": value})
    return points


def _comparison(actual: float | int | None, operator: str, expected: float | int) -> bool:
    if actual is None or isinstance(actual, bool):
        return False
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    if operator == "==":
        return actual == expected
    if operator == ">=":
        return actual >= expected
    if operator == ">":
        return actual > expected
    raise SloWindowError(f"unsupported comparator operator: {operator}")


def _passes(contract: dict[str, Any], key: str, value: float | int) -> bool:
    comparator = contract.get("comparators", {}).get(key, {})
    baseline = contract.get("baseline", {})
    if key == "contractFailureRate":
        comparator = contract.get("comparators", {}).get("baselineContractFailureRate", {})
    if not comparator:
        comparator = {"operator": "<=" if key == "p95Ms" else ">=", "value": baseline.get(key)}
    return _comparison(value, str(comparator.get("operator")), comparator.get("value"))


def window_stage_fields(metadata: dict[str, Any], start: float) -> dict[str, Any]:
    """Join a closed window to the preregistered stress schedule."""
    inputs = metadata.get("effectiveInputs") if isinstance(metadata.get("effectiveInputs"), dict) else {}
    multipliers = inputs.get("stageMultipliers")
    durations = inputs.get("stageDurations")
    started = timestamp(metadata.get("startedAtUtc"))
    if not isinstance(multipliers, list) or not isinstance(durations, list) or len(multipliers) != len(durations) or started is None:
        return {"stageIndex": None, "stageMultiplier": None}
    parsed = [duration_seconds(value) for value in durations]
    if any(value is None for value in parsed):
        return {"stageIndex": None, "stageMultiplier": None}
    elapsed = max(0.0, start - started)
    cursor = 0.0
    selected = len(multipliers) - 1
    for index, duration in enumerate(parsed):
        assert duration is not None
        if elapsed < cursor + duration:
            selected = index
            break
        cursor += duration
    return {"stageIndex": selected, "stageMultiplier": multipliers[selected]}


def window_payload(points: Iterable[dict[str, Any]], start: float, contract: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    end = start + 60.0
    selected = [item for item in points if start <= item["ts"] < end]
    counters = {name: 0 for name in ALL_COUNTERS}
    durations: list[float] = []
    for item in selected:
        metric = item["metric"]
        if metric in ALL_COUNTERS:
            counters[metric] += int(item["value"])
        elif metric == "http_req_duration":
            durations.append(item["value"])
    completed = counters["core_completed_operations_total"]
    successful = counters["core_successful_operations_total"]
    unexpected = counters["core_unexpected_errors_total"]
    contract_failures = counters["core_contract_failures_total"]
    p95 = percentile(durations, 0.95)
    success_rate = successful / completed if completed else None
    unexpected_rate = unexpected / completed if completed else None
    contract_rate = contract_failures / completed if completed else None
    dropped = counters["dropped_iterations"]
    achieved_rps = counters["iterations"] / 60.0
    complete = completed > 0 and p95 is not None and success_rate is not None and unexpected_rate is not None and contract_rate is not None
    breach = None
    if complete:
        breach = not (
            _passes(contract, "p95Ms", p95)
            and _passes(contract, "successRate", success_rate)
            and _passes(contract, "unexpectedErrorRate", unexpected_rate)
            and _passes(contract, "contractFailureRate", contract_rate)
            and _passes(contract, "droppedIterations", dropped)
        )
    stage = window_stage_fields(metadata, start)
    return {
        "sloWindow": True,
        "sloWindowId": f"{int(start)}-{int(end)}",
        "sloWindowStartUtc": iso(start),
        "sloWindowEndUtc": iso(end),
        "sloWindowSeconds": 60,
        "sloWindowComplete": complete,
        "sloWindowSource": "k6-raw-core-metrics",
        "coreCounts": counters,
        "coreCompletedOperations": completed,
        "p95Ms": p95,
        "successRate": success_rate,
        "unexpectedErrorRate": unexpected_rate,
        "contractFailureRate": contract_rate,
        "droppedIterations": dropped,
        "achievedRps": achieved_rps,
        "sloBreached": breach,
        "stageIndex": stage["stageIndex"],
        "stageMultiplier": stage["stageMultiplier"],
        "profileSha256": metadata.get("profileSha256"),
        "runId": metadata.get("runId"),
    }


def produce(input_path: Path, output_path: Path, metadata_path: Path, contract_path: Path, *, finalize: bool = False) -> int:
    metadata = read_metadata(metadata_path)
    contract = read_contract(contract_path)
    started = timestamp(metadata.get("startedAtUtc"))
    assert started is not None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    emitted: set[str] = set()
    if output_path.is_file():
        for line in output_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and isinstance(item.get("sloWindowId"), str):
                emitted.add(item["sloWindowId"])

    while True:
        points = read_points(input_path)
        latest = max((item["ts"] for item in points), default=None)
        if latest is not None:
            completed_until = int((latest - started) // 60)
            for index in range(max(0, completed_until)):
                window = window_payload(points, started + index * 60, contract, metadata)
                if window["sloWindowId"] in emitted:
                    continue
                with output_path.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(window, sort_keys=True) + "\n")
                    output.flush()
                emitted.add(window["sloWindowId"])
        if finalize:
            return 0
        # Stop only when the producer is explicitly told to finalize; the
        # caller owns the k6 process lifecycle and sends SIGTERM/SIGINT.
        time.sleep(max(0.1, float(getattr(produce, "poll_seconds", 2.0))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="append-only k6 raw.json")
    parser.add_argument("--output", required=True, type=Path, help="append-only slo-windows.jsonl")
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--slo-contract", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true", help="scan once and exit")
    parser.add_argument("--finalize", action="store_true", help="emit all complete windows and exit")
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    produce.poll_seconds = args.poll_seconds
    return produce(args.input, args.output, args.metadata, args.slo_contract, finalize=args.once or args.finalize)


if __name__ == "__main__":
    raise SystemExit(main())
