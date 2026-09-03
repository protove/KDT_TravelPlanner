#!/usr/bin/env python3
"""Run a Capacity/Scale Stress workload with read-only terminal polling.

The coordinator owns only process timing and a local, append-only snapshot
file. A separate observer may write sanitized JSON snapshots containing
platform state and metrics; this process never writes AWS desired state,
cancels refreshes, restores images, rolls back Kubernetes or destroys
resources. Adaptive v2 stages have no RPS completion ceiling. They stop at
the nominal five-minute boundary unless an in-flight scale transition is
still active, then allow one bounded three-minute extension. A clean stage
boundary is ``STAGE_COMPLETE`` and is deliberately not a successful
breakpoint.
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
    "NODE_MAX_PENDING", "NODE_SCALE_NOT_TRIGGERED", "NODE_SCALE_FAILED",
    "NODE_COMPUTE_SATURATION", "SLO_COLLAPSE", "THROUGHPUT_PLATEAU",
    "HPA_CAPACITY_EXHAUSTED", "BACKEND_OOM", "BACKEND_UNHEALTHY",
    "ALB_SATURATION", "DATA_TIER_SATURATION",
    # Legacy v1 outcomes remain parseable for historical evidence only.
    "MAX_CAPACITY_REACHED", "PROFILE_COMPLETE", "HARD_CEILING",
)

ACTUAL_TERMINAL_REASONS = {
    "NODE_MAX_PENDING", "NODE_SCALE_NOT_TRIGGERED", "NODE_SCALE_FAILED",
    "NODE_COMPUTE_SATURATION", "SLO_COLLAPSE", "THROUGHPUT_PLATEAU",
    "HPA_CAPACITY_EXHAUSTED", "BACKEND_OOM", "BACKEND_UNHEALTHY",
    "ALB_SATURATION", "DATA_TIER_SATURATION",
}


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


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def extension_allowed(snapshots: list[dict]) -> bool:
    """Return whether the latest snapshot proves an active scale transition."""
    if not snapshots:
        return False
    item = snapshots[-1]
    hpa = item.get("hpa") if isinstance(item.get("hpa"), dict) else {}
    deployment = item.get("deployment") if isinstance(item.get("deployment"), dict) else {}
    pods = item.get("backendPods") if isinstance(item.get("backendPods"), dict) else {}
    capacity = item.get("capacity") if isinstance(item.get("capacity"), dict) else {}
    desired = _number(hpa.get("desiredReplicas"))
    ready = _number(deployment.get("readyReplicas"))
    if desired is not None and ready is not None and desired > ready:
        return True
    pending_count = _number(pods.get("pendingCount"))
    if pending_count is not None and pending_count > 0:
        return True
    pending_reasons = pods.get("pendingReasons") or item.get("pendingReasons")
    if isinstance(pending_reasons, list) and any(
        any(word in str(reason).lower() for word in ("schedul", "insufficient", "resource"))
        for reason in pending_reasons
    ):
        return True
    if item.get("caActivityActive") is True or item.get("nodeScaleInProgress") is True:
        return True
    node_desired = _number(capacity.get("desired"))
    ready_nodes = _number(item.get("readyNodeCount"))
    if node_desired is not None and ready_nodes is not None and node_desired > ready_nodes:
        return True
    if item.get("newNodeNotReady") is True:
        return True
    if item.get("newPodNotReady") is True and item.get("albHealthy") is not False:
        return True
    return False


def backend_unhealthy_terminal(item: dict) -> bool:
    """Keep readiness lag separate from a real backend runtime failure.

    During an adaptive EKS stage a Deployment can temporarily report
    ``unavailableReplicas`` while HPA has increased the desired count and a
    new Pod/Node is still becoming ready. Treating that transient gap as
    ``BACKEND_UNHEALTHY`` ends the breakpoint before autoscaling converges.
    Restarts or an observed CrashLoop remain a real backend terminal;
    readiness-only gaps are left to the SLO/throughput and pending contracts.
    """
    if item.get("backendUnhealthy") is not True:
        return False
    restart_count = item.get("backendRestartCount")
    try:
        if float(restart_count) > 0:
            return True
    except (TypeError, ValueError):
        pass
    pods = item.get("backendPods") if isinstance(item.get("backendPods"), dict) else {}
    placements = pods.get("placement") if isinstance(pods.get("placement"), list) else []
    if any(isinstance(pod, dict) and pod.get("crashLoopBackOff") is True for pod in placements):
        return True
    # unavailableReplicas without a restart/CrashLoop is a readiness gap.
    return False


def terminal_reason(snapshots: list[dict], stability_seconds: int) -> str | None:
    # A desired/ready node count of four is only scale-out evidence. Maximum
    # capacity is terminal only when the observer explicitly proves a
    # max-node Pending/scheduling ceiling or emits maxCapacityReached.
    for reason, key in (
        ("BACKEND_OOM", "backendOom"),
        ("ALB_SATURATION", "albSaturated"),
        ("NODE_SCALE_FAILED", "nodeScaleFailed"),
        ("NODE_SCALE_NOT_TRIGGERED", "nodeScaleNotTriggered"),
        ("NODE_COMPUTE_SATURATION", "nodeComputeSaturated"),
    ):
        if true_for_seconds(snapshots, lambda item, field=key: item.get(field) is True, stability_seconds):
            return reason

    if true_for_seconds(snapshots, backend_unhealthy_terminal, stability_seconds):
        return "BACKEND_UNHEALTHY"

    if true_for_seconds(snapshots, lambda item: item.get("hpaCapacityExhausted") is True, stability_seconds):
        return "HPA_CAPACITY_EXHAUSTED"

    if true_for_seconds(
        snapshots,
        lambda item: item.get("throughputPlateau") is True and item.get("runnerValid", True) is not False,
        stability_seconds,
    ):
        return "THROUGHPUT_PLATEAU"

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
    # A fixed-arrival k6 stage can finish naturally at the same instant that
    # the observer records a sustained terminal condition.  Give the wrapper
    # a short grace period first so k6 can run handleSummary and flush
    # k6-native-summary.json/summary.json.  Without this race guard the group
    # SIGINT below can turn an otherwise complete stage into exit 2 with no
    # summary, making a valid terminal observation look incomplete.
    try:
        process.wait(timeout=5)
        append_event(
            event_handle,
            "WORKLOAD_NATURAL_EXIT",
            reason=reason,
            workloadExitCode=process.returncode,
            actor="capacity-coordinator",
        )
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        # The workload command is a shell that owns the Docker/k6 child.  A
        # signal sent only to that shell can leave k6 running until the
        # escalation timeout, producing exit 137 and no summary.json.  The
        # child is launched in its own process group below, so signal the
        # complete group and let k6 flush its summary/JSON output gracefully.
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        append_event(event_handle, "WORKLOAD_TERM_ESCALATION", reason=reason, actor="capacity-coordinator")
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
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
    parser.add_argument("--adaptive", action="store_true", help="Use one-target v2 stage timing")
    parser.add_argument("--nominal-hold-seconds", type=int, default=300)
    parser.add_argument("--conditional-extension-seconds", type=int, default=180)
    parser.add_argument("--max-stage-seconds", type=int, default=480)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument(
        "--campaign-stage",
        choices=(
            "capacity-stress", "pod-scale-out", "node-scale-out-breakpoint", "recovery",
            "hotspot-1", "hotspot-2", "spike-256", "recovery-16",
        ),
        default="capacity-stress",
    )
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
    if args.adaptive and (
        args.nominal_hold_seconds < 1
        or args.conditional_extension_seconds < 1
        or args.max_stage_seconds < args.nominal_hold_seconds
        or args.max_stage_seconds > args.nominal_hold_seconds + args.conditional_extension_seconds
    ):
        parser.error("adaptive stage timing must be nominal + at most one extension")
    return args


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = (args.snapshot_file or run_dir / "snapshots.jsonl").resolve()
    events_path = run_dir / "controller-events.jsonl"
    result_path = run_dir / "controller-result.json"
    started = time.monotonic()
    controller_started_at = utc_now()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]

    with events_path.open("w", encoding="utf-8") as events:
        append_event(events, "CONTROLLER_START", command=command, snapshotFile=str(snapshot_file), campaignStage=args.campaign_stage, controllerStartedAtUtc=controller_started_at)
        process = subprocess.Popen(
            command,
            cwd=os.getcwd(),
            env=os.environ.copy(),
            start_new_session=True,
        )
        append_event(events, "WORKLOAD_STARTED", pid=process.pid)
        reason: str | None = None
        extension_started = False
        while process.poll() is None:
            snapshots = read_json_lines(snapshot_file)
            reason = terminal_reason(snapshots, args.capacity_stability_seconds)
            elapsed = time.monotonic() - started
            if reason:
                terminate_process(process, events, reason)
                break
            if args.adaptive:
                if elapsed >= args.max_stage_seconds:
                    reason = "STAGE_COMPLETE"
                    terminate_process(process, events, reason)
                    break
                if elapsed >= args.nominal_hold_seconds and not extension_started:
                    if extension_allowed(snapshots):
                        extension_started = True
                        append_event(
                            events,
                            "STAGE_EXTENSION",
                            seconds=args.conditional_extension_seconds,
                            actor="capacity-coordinator",
                        )
                    else:
                        reason = "STAGE_COMPLETE"
                        terminate_process(process, events, reason)
                        break
            elif elapsed >= args.hard_time_ceiling_seconds:
                reason = "HARD_CEILING"
                terminate_process(process, events, reason)
                break
            time.sleep(args.poll_seconds)
        exit_code = process.wait()
        elapsed = time.monotonic() - started
        if reason is None:
            if args.adaptive:
                reason = "STAGE_COMPLETE"
            else:
                # Legacy finite schedules remain parseable for historical
                # evidence, but are never valid v2 breakpoint outcomes.
                reason = (
                    "PROFILE_COMPLETE"
                    if elapsed >= args.complete_schedule_seconds and exit_code == 0
                    else "HARD_CEILING"
                    if elapsed >= args.hard_time_ceiling_seconds
                    else "WORKLOAD_COMPLETED"
                )
        append_event(events, "CONTROLLER_END", terminalReason=reason, workloadExitCode=exit_code, elapsedSeconds=round(elapsed, 3))

    workload_actual_start = None
    status_path = run_dir / "run-status.json"
    if status_path.is_file():
        try:
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            candidate = status_payload.get("actualOperationStartAtUtc") if isinstance(status_payload, dict) else None
            workload_actual_start = candidate if isinstance(candidate, str) and candidate else None
        except (OSError, json.JSONDecodeError):
            workload_actual_start = None
    write_json(result_path, {
        "schemaVersion": "capacity-stress-controller/v2" if args.adaptive else "capacity-stress-controller/v1",
        "startedAtUtc": controller_started_at,
        "controllerStartedAtUtc": controller_started_at,
        "workloadActualOperationStartAtUtc": workload_actual_start,
        "endedAtUtc": utc_now(),
        "terminalReason": reason,
        "workloadExitCode": exit_code,
        "elapsedSeconds": round(elapsed, 3),
        "capacityStabilitySeconds": args.capacity_stability_seconds,
        "completeScheduleSeconds": args.complete_schedule_seconds,
        "hardTimeCeilingSeconds": args.hard_time_ceiling_seconds,
        "adaptive": args.adaptive,
        "nominalHoldSeconds": args.nominal_hold_seconds if args.adaptive else None,
        "conditionalExtensionSeconds": args.conditional_extension_seconds if args.adaptive else None,
        "maxStageSeconds": args.max_stage_seconds if args.adaptive else None,
        "extensionStarted": extension_started,
        "snapshotFile": str(snapshot_file),
        "campaignStage": args.campaign_stage,
        "workloadCommandRecorded": True,
        "operatorRecoveryAutomated": False,
        "autoscalingDesiredStateWritten": False,
        # A SIGINT at an adaptive clean boundary is an orchestration event,
        # not an interrupted/unknown workload.  Persist the distinction so
        # continuity can reject an operator interruption while allowing a
        # stage that has its required complete healthy windows.
        "intentionalStageBoundary": bool(args.adaptive and reason == "STAGE_COMPLETE"),
    })
    if args.adaptive and reason == "STAGE_COMPLETE":
        return 0
    return 0 if exit_code == 0 or reason in TERMINAL_REASONS else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
