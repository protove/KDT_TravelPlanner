#!/usr/bin/env python3
"""Validate timing invariants before a Compose rehearsal starts."""

from __future__ import annotations

import argparse
import re
import sys


DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
MIN_POST_DRILL_SECONDS = 180


def duration_seconds(value: str) -> float:
    consumed = 0
    total = 0.0
    multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    for match in DURATION_PATTERN.finditer(value):
        if match.start() != consumed:
            raise ValueError(f"invalid duration: {value}")
        total += float(match.group(1)) * multipliers[match.group(2)]
        consumed = match.end()
    if consumed != len(value) or total <= 0:
        raise ValueError(f"invalid duration: {value}")
    return total


def validate(*, mode: str, warmup: str, baseline: str, recovery: str, drill_at_min: int) -> None:
    warmup_seconds = duration_seconds(warmup)
    if warmup_seconds % 60 != 0:
        raise ValueError("warm-up must use whole minutes (for example 3m)")
    if mode in {"baseline", "all"}:
        duration_seconds(baseline)
    if mode in {"recovery", "all"}:
        recovery_seconds = duration_seconds(recovery)
        drill_seconds = drill_at_min * 60
        if drill_seconds <= warmup_seconds:
            raise ValueError(
                f"drill-at {drill_at_min}m must be after the warm-up window {warmup}"
            )
        required = drill_seconds + MIN_POST_DRILL_SECONDS
        if recovery_seconds < required:
            raise ValueError(
                f"recovery duration {recovery} is shorter than drill-at {drill_at_min}m "
                f"plus the mandatory {MIN_POST_DRILL_SECONDS}s observation window"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "baseline", "recovery", "spike", "all"), required=True)
    parser.add_argument("--warmup", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--recovery", required=True)
    parser.add_argument("--drill-at-min", type=int, required=True)
    args = parser.parse_args()
    if args.drill_at_min < 0:
        parser.error("--drill-at-min must be zero or greater")
    try:
        validate(
            mode=args.mode,
            warmup=args.warmup,
            baseline=args.baseline,
            recovery=args.recovery,
            drill_at_min=args.drill_at_min,
        )
    except ValueError as error:
        print(f"[config] ERROR: {error}", file=sys.stderr)
        return 2
    print("[config] rehearsal timing contract is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
