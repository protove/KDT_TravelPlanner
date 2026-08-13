#!/usr/bin/env python3
"""Derive client-observed failure timing for a Compose recovery run."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def timestamp(value: str) -> float:
    match = re.fullmatch(r"(.+\.)(\d+)(Z|[+-]\d{2}:\d{2})", value)
    if match:
        value = f"{match.group(1)}{match.group(2)[:6].ljust(6, '0')}{match.group(3)}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: derive-rehearsal-events.py <run-dir>", file=sys.stderr)
        return 2
    run_dir = Path(sys.argv[1])
    operations = run_dir / "operations.jsonl"
    raw = run_dir / "raw.json"
    events = [json.loads(line) for line in operations.read_text(encoding="utf-8").splitlines()]
    if any(entry["event"] == "T3" for entry in events):
        return 0
    t1 = next((timestamp(entry["ts"]) for entry in events if entry["event"] == "T1"), None)
    if t1 is None or not raw.exists():
        return 0
    first_failure = None
    for line in raw.read_text(encoding="utf-8").splitlines():
        try:
            point = json.loads(line)
        except json.JSONDecodeError:
            continue
        if point.get("type") != "Point" or point.get("metric") != "unexpected_errors":
            continue
        data = point.get("data", {})
        point_time = timestamp(data["time"])
        if point_time >= t1 and data.get("value") == 1:
            first_failure = point_time
            break
    if first_failure is None:
        return 0
    with operations.open("a", encoding="utf-8") as output:
        output.write(json.dumps({
            "ts": datetime.fromtimestamp(first_failure, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "event": "T3",
            "detail": "first client-observed unexpected error; Compose proxy for detection timing, not an AWS Alarm",
            "actor": "evaluator",
        }) + "\n")
    print(f"[event] T3 derived at {first_failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
