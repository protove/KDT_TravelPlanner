#!/usr/bin/env python3
"""Run a Capacity/Scale Stress workload with read-only terminal polling.

The coordinator owns only process timing and a local, append-only snapshot
file. A separate observer may write sanitized JSON snapshots containing
platform state and metrics; this process never writes AWS desired state,
cancels refreshes, restores images, rolls back Kubernetes or destroys
resources. If no observer snapshots arrive, the workload is allowed to reach
the preregistered hard ceiling and the missing metric window is reported by
the evaluator rather than guessed.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


TERMINAL_REASONS = (
    "MAX_CAPACITY_REACHED",
    "NODE_MAX_PENDING",
    "SLO_COLLAPSE",
    "DATA_TIER_SATURATION",
    "PROFILE_COMPLETE",
    "HARD_CEILING",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    snapshots: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            snapshots.append(value)
    return snapshots


def timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def true_for_seconds(snapshots: list[dict], predicate, seconds: float) -> bool:
    active_since: float | None = None
    for snapshot in snapshots:
        ts = timestamp(snapshot.get("ts") or snapshot.get("timestamp"))
        if ts is None:
            continue
        if predicate(snapshot):
            if active_since is None:
                active_since = ts
            if ts - active_since >= seconds:
                return True
        else:
            active_since = None
    return False


def terminal_reason(snapshots: list[dict], stability_seconds: int) -> str | None:
    # A desired/ready node count of four is only scale-out evidence. Maximum
    # capacity is terminal only when the observer explicitly proves a
    # max-node Pending/scheduling ceiling or emits maxCapacityReached.
    if true_for_seconds(snapshots, lambda item: item.get("maxCapacityReached") is True, stability_seconds):
        return "MAX_CAPACITY_REACHED"

    if true_for_seconds(snapshots, lambda item: item.get("nodeMaxPending") is True, stability_seconds):
        return "NODE_MAX_PENDING"

    # The observer should emit one 60-second SLO window per entry. Requiring
    # two marked windows keeps the evaluator independent of polling cadence.
    slo_windows = [
        item for item in snapshots
        if item.get("sloWindow") is True
        and item.get("sloBreached") is True
        and (item.get("sloWindowComplete") is True or item.get("sloWindowSeconds") == 60)
    ]
    if len(slo_windows) >= 2:
        first = timestamp(slo_windows[-2].get("ts") or slo_windows[-2].get("timestamp"))
        last = timestamp(slo_windows[-1].get("ts") or slo_windows[-1].get("timestamp"))
        if first is not None and last is not None and last - first >= 60:
            return "SLO_COLLAPSE"

    if true_for_seconds(
        snapshots,
        lambda item: item.get("dataTierSaturated") is True,
        stability_seconds,
    ):
        return "DATA_TIER_SATURATION"
    return None


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_event(handle, event: str, **fields: object) -> None:
    payload = {"ts": utc_now(), "event": event, **fields}
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
    handle.flush()


def terminate_process(process: subprocess.Popen, event_handle, reason: str) -> None:
    if process.poll() is not None:
        return
    append_event(event_handle, "WORKLOAD_STOP_REQUESTED", reason=reason, actor="capacity-coordinator")
    try:
        process.send_signal(signal.SIGINT)
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        append_event(event_handle, "WORKLOAD_TERM_ESCALATION", reason=reason, actor="capacity-coordinator")
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--snapshot-file", type=Path)
    parser.add_argument("--capacity-stability-seconds", type=int, default=120)
    parser.add_argument(
        "--complete-schedule-seconds",
        type=int,
        default=1740,
        help="Expected 1x/2x/4x/8x schedule length; a clean exit at or beyond it is HARD_CEILING.",
    )
    parser.add_argument("--hard-time-ceiling-seconds", type=int, default=2100)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--", dest="separator", nargs="?")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a workload command is required after the coordinator options")
    if args.capacity_stability_seconds < 1 or args.complete_schedule_seconds < 1 or args.hard_time_ceiling_seconds < 1:
        parser.error("terminal durations must be positive")
    if args.complete_schedule_seconds > args.hard_time_ceiling_seconds:
        parser.error("complete schedule cannot exceed the hard time ceiling")
    if args.poll_seconds <= 0:
        parser.error("poll interval must be positive")
    return args


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = (args.snapshot_file or run_dir / "snapshots.jsonl").resolve()
    events_path = run_dir / "controller-events.jsonl"
    result_path = run_dir / "controller-result.json"
    started = time.monotonic()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]

    with events_path.open("w", encoding="utf-8") as events:
        append_event(events, "CONTROLLER_START", command=command, snapshotFile=str(snapshot_file))
        process = subprocess.Popen(command, cwd=os.getcwd(), env=os.environ.copy())
        append_event(events, "WORKLOAD_STARTED", pid=process.pid)
        reason: str | None = None
        while process.poll() is None:
            snapshots = read_json_lines(snapshot_file)
            reason = terminal_reason(snapshots, args.capacity_stability_seconds)
            elapsed = time.monotonic() - started
            if reason:
                terminate_process(process, events, reason)
                break
            if elapsed >= args.hard_time_ceiling_seconds:
                reason = "HARD_CEILING"
                terminate_process(process, events, reason)
                break
            time.sleep(args.poll_seconds)
        exit_code = process.wait()
        elapsed = time.monotonic() - started
        if reason is None:
            # A clean exit after the preregistered schedule is profile
            # completion, distinct from a hard time ceiling. Anything shorter
            # remains WORKLOAD_COMPLETED and the evaluator rejects it.
            reason = (
                "PROFILE_COMPLETE"
                if elapsed >= args.complete_schedule_seconds and exit_code == 0
                else "HARD_CEILING"
                if elapsed >= args.hard_time_ceiling_seconds
                else "WORKLOAD_COMPLETED"
            )
        append_event(events, "CONTROLLER_END", terminalReason=reason, workloadExitCode=exit_code, elapsedSeconds=round(elapsed, 3))

    write_json(result_path, {
        "schemaVersion": "capacity-stress-controller/v1",
        "startedAtUtc": utc_now(),
        "terminalReason": reason,
        "workloadExitCode": exit_code,
        "elapsedSeconds": round(elapsed, 3),
        "capacityStabilitySeconds": args.capacity_stability_seconds,
        "completeScheduleSeconds": args.complete_schedule_seconds,
        "hardTimeCeilingSeconds": args.hard_time_ceiling_seconds,
        "snapshotFile": str(snapshot_file),
        "workloadCommandRecorded": True,
        "operatorRecoveryAutomated": False,
        "autoscalingDesiredStateWritten": False,
    })
    return 0 if exit_code == 0 or reason in TERMINAL_REASONS else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
