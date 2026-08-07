#!/usr/bin/env python3
"""Append one sanitized UTC event to a rehearsal operations.jsonl file."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_EVENTS = {"T1", "T2", "T3", "T4", "T5", "T5_FAIL", "T6", "RUN_START", "RUN_END"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("event", choices=sorted(ALLOWED_EVENTS))
    parser.add_argument("detail", nargs="?", default="")
    parser.add_argument("--actor", default="operator")
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event": args.event,
        "detail": args.detail,
        "actor": args.actor,
    }
    with (args.run_dir / "operations.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[event] {entry['ts']} {args.event}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
