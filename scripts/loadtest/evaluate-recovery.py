#!/usr/bin/env python3
"""Evaluate the Compose recovery window from k6 JSON points."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


P95_MS = 500.0
UNEXPECTED_ERROR_RATE = 0.01
CAPACITY_FLOOR = 0.90


def timestamp(value: str) -> float:
    # k6 may emit nanosecond precision while Python's stdlib accepts at most
    # microseconds in fromisoformat(). Keep the timestamp timezone intact and
    # truncate only excess fractional precision.
    match = re.fullmatch(r"(.+\.)(\d+)(Z|[+-]\d{2}:\d{2})", value)
    if match:
        value = f"{match.group(1)}{match.group(2)[:6].ljust(6, '0')}{match.group(3)}"
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).timestamp()


def load_points(path: Path, bucket_seconds: int) -> tuple[dict, dict, dict, float | None]:
    durations: defaultdict[int, list[float]] = defaultdict(list)
    unexpected_failures: defaultdict[int, list[int]] = defaultdict(lambda: [0, 0])
    contract_failures: defaultdict[int, list[int]] = defaultdict(lambda: [0, 0])
    successes: defaultdict[int, int] = defaultdict(int)
    minimum_timestamp: float | None = None
    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            try:
                point = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if point.get("type") != "Point" or "data" not in point:
                continue
            data = point["data"]
            point_timestamp = timestamp(data["time"])
            minimum_timestamp = (
                point_timestamp if minimum_timestamp is None else min(minimum_timestamp, point_timestamp)
            )
            bucket = math.floor(point_timestamp / bucket_seconds) * bucket_seconds
            metric = point.get("metric")
            if metric == "http_req_duration":
                durations[bucket].append(float(data["value"]))
            elif metric == "unexpected_errors":
                unexpected_failures[bucket][0] += 1
                unexpected_failures[bucket][1] += int(data["value"] == 1)
            elif metric == "contract_fail":
                contract_failures[bucket][0] += 1
                contract_failures[bucket][1] += int(data["value"] == 1)
            elif metric == "successful_requests":
                successes[bucket] += int(data["value"])
    return {"durations": durations, "successes": successes}, unexpected_failures, contract_failures, minimum_timestamp


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return math.inf
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile_value
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def evaluate_bucket(
    bucket: int,
    points: dict,
    unexpected_failures: dict,
    contract_failures: dict,
    base_success_rps: float,
    bucket_seconds: int,
) -> bool:
    durations = points["durations"].get(bucket, [])
    if not durations:
        return False
    unexpected_total, unexpected_count = unexpected_failures.get(bucket, [0, 0])
    contract_total, contract_count = contract_failures.get(bucket, [0, 0])
    unexpected_rate = unexpected_count / unexpected_total if unexpected_total else 0.0
    contract_rate = contract_count / contract_total if contract_total else 0.0
    success_rps = points["successes"].get(bucket, 0) / bucket_seconds
    return (
        percentile(durations, 0.95) <= P95_MS
        and unexpected_rate < UNEXPECTED_ERROR_RATE
        and contract_rate < UNEXPECTED_ERROR_RATE
        and success_rps >= CAPACITY_FLOOR * base_success_rps
    )


def read_events(path: Path) -> dict[str, float]:
    events: dict[str, float] = {}
    if not path.exists():
        return events
    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            entry = json.loads(raw_line)
            events.setdefault(entry["event"], timestamp(entry["ts"]))
    return events


def evaluate(args: argparse.Namespace) -> dict:
    points, unexpected_failures, contract_failures, first_timestamp = load_points(
        args.run_dir / "raw.json", args.bucket,
    )
    if first_timestamp is None:
        raise ValueError("raw.json contains no k6 Point data")
    events = read_events(args.run_dir / "operations.jsonl")
    warmup_end = first_timestamp + args.warmup_sec
    intervention = events.get(args.recovery_event)
    base_buckets = [
        bucket for bucket in points["durations"]
        if bucket + args.bucket > warmup_end and (intervention is None or bucket < intervention)
    ]
    if not base_buckets:
        raise ValueError("normal baseline window is empty")
    base_success_rps = statistics.median(
        points["successes"].get(bucket, 0) / args.bucket for bucket in base_buckets
    )
    if base_success_rps <= 0:
        raise ValueError("normal baseline contains no successful requests")

    t6 = None
    if intervention is not None:
        candidate_buckets = sorted(bucket for bucket in points["durations"] if bucket >= intervention)
        required_buckets = max(1, math.ceil(args.window_sec / args.bucket))
        for index in range(0, len(candidate_buckets) - required_buckets + 1):
            window = candidate_buckets[index:index + required_buckets]
            if window[-1] - window[0] != (required_buckets - 1) * args.bucket:
                continue
            if all(
                evaluate_bucket(
                    bucket,
                    points,
                    unexpected_failures,
                    contract_failures,
                    base_success_rps,
                    args.bucket,
                )
                for bucket in window
            ):
                t6 = window[-1] + args.bucket
                break

    recovery_seconds = round(t6 - intervention, 1) if t6 is not None and intervention is not None else None
    capacity_values = [
        points["successes"].get(bucket, 0) / args.bucket / base_success_rps
        for bucket in points["durations"]
        if intervention is not None and bucket >= intervention
    ]
    result = {
        "baseSuccessfulRpsMedian": round(base_success_rps, 2),
        "capacityFloorRatio": round(min(capacity_values), 3) if capacity_values else None,
        "T1": events.get("T1"),
        "T4": events.get("T4"),
        "T5": events.get("T5"),
        "T6": t6,
        "recoveryEvent": args.recovery_event,
        "recoverySeconds": recovery_seconds,
        "budgetSeconds": args.budget_sec,
        "withinBudget": recovery_seconds is not None and recovery_seconds <= args.budget_sec,
        "effectiveReentryDeadlineSeconds": args.budget_sec - args.window_sec,
        "sloVersion": "v0.1-draft (Compose pipeline rehearsal; not an AWS pass/fail claim)",
    }
    (args.run_dir / "verdict.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--warmup-sec", type=int, default=180)
    parser.add_argument("--window-sec", type=int, default=120)
    parser.add_argument("--budget-sec", type=int, default=600)
    parser.add_argument("--bucket", type=int, default=10)
    parser.add_argument("--recovery-event", default="T1")
    args = parser.parse_args()
    result = evaluate(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["withinBudget"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[verdict] ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
