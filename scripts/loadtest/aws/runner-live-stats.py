#!/usr/bin/env python3
"""Report a sliding-window summary of a live AWS Recovery k6 raw.json file.

The coordinator polls this helper over SSM while the workload is running to
verify the pre-T1 normal window and to detect k6-observed Core API errors
(R-07). It reads only the tail of raw.json, never mutates anything, and
prints a single sanitized JSON object to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


WINDOW_METRICS = (
    "core_operations_total",
    "core_completed_operations_total",
    "core_successful_operations_total",
    "core_unexpected_errors_total",
    "core_contract_failures_total",
)
# A recovery run emits several JSON points per iteration (HTTP metrics plus
# the Core counters). At the frozen 16-iteration/s rate an 8 MiB tail can cover
# less than the coordinator's 120-second window, undercounting a healthy
# pre-T1 workload and blocking T1. Keep the default tail comfortably wider
# than the fixed window while retaining the explicit --tail-bytes escape hatch.
DEFAULT_TAIL_BYTES = 64 * 1024 * 1024


def parse_timestamp(value: str) -> float:
    trimmed = value
    if "." in value:
        head, _, rest = value.partition(".")
        digits = ""
        for char in rest:
            if char.isdigit():
                digits += char
            else:
                break
        suffix = rest[len(digits):]
        trimmed = f"{head}.{digits[:6].ljust(6, '0')}{suffix}"
    return datetime.fromisoformat(trimmed.replace("Z", "+00:00")).timestamp()


def read_tail_lines(path: Path, tail_bytes: int) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > tail_bytes:
            handle.seek(size - tail_bytes)
            handle.readline()  # drop the partial first line
        return handle.read().decode("utf-8", errors="replace").splitlines()


def summarize(path: Path, window_seconds: int, tail_bytes: int, now: float | None = None) -> dict:
    if not path.is_file():
        return {"status": "missing", "rawJson": path.name}
    totals = {metric: 0.0 for metric in WINDOW_METRICS}
    latest_point: float | None = None
    for line in read_tail_lines(path, tail_bytes):
        if '"Point"' not in line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        metric = payload.get("metric")
        data = payload.get("data")
        if metric not in totals or not isinstance(data, dict):
            continue
        try:
            point_time = parse_timestamp(str(data.get("time")))
        except (TypeError, ValueError):
            continue
        if latest_point is None or point_time > latest_point:
            latest_point = point_time
        reference = now if now is not None else datetime.now(timezone.utc).timestamp()
        if point_time >= reference - window_seconds:
            value = data.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[metric] += float(value)
    reference = now if now is not None else datetime.now(timezone.utc).timestamp()
    return {
        "status": "ok",
        "windowSeconds": window_seconds,
        "generatedAtUtc": datetime.fromtimestamp(reference, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "latestPointAgeSeconds": (
            round(reference - latest_point, 3) if latest_point is not None else None
        ),
        "operations": totals["core_operations_total"],
        "completed": totals["core_completed_operations_total"],
        "successful": totals["core_successful_operations_total"],
        "unexpectedErrors": totals["core_unexpected_errors_total"],
        "contractFailures": totals["core_contract_failures_total"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Recovery run directory containing raw.json")
    parser.add_argument("--window-seconds", type=int, default=120)
    parser.add_argument("--tail-bytes", type=int, default=DEFAULT_TAIL_BYTES)
    args = parser.parse_args(argv)
    if args.window_seconds <= 0 or args.tail_bytes <= 0:
        print("window-seconds and tail-bytes must be positive", file=sys.stderr)
        return 2
    result = summarize(args.run_dir / "raw.json", args.window_seconds, args.tail_bytes)
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
