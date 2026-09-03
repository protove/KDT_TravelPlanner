#!/usr/bin/env python3
"""Fail-closed continuity check for an adaptive EKS load-test handoff.

This is intentionally a small, read-only gate.  It never changes Kubernetes,
AWS, k6, or a workload.  The caller must run it immediately before dispatching
the next high-rate segment.  A stage is ``ALLOW`` only when the evidence proves
two complete healthy 60-second windows, fresh observations, and stable Pod /
Node identity.  A cold or interrupted stage returns ``RESTORE_LOW`` so the
caller can requalify from a measured predecessor; unknown evidence returns
``BLOCK``.  Counts alone are never sufficient.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ALLOW = 0
RESTORE_LOW = 10
BLOCK = 20


def parse_time(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _identity_rows(snapshot: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    pods = snapshot.get("backendPods")
    placements = pods.get("placement") if isinstance(pods, Mapping) else None
    if isinstance(placements, list):
        yield from (row for row in placements if isinstance(row, Mapping))
    nodes = snapshot.get("readyNodes")
    if isinstance(nodes, list):
        yield from (row for row in nodes if isinstance(row, Mapping))


def _stable_snapshot(snapshot: Mapping[str, Any], target_rate: float | None = None) -> bool:
    """Return true only for a complete healthy observation."""
    if snapshot.get("requiredObservationsValid") is not True:
        return False
    if snapshot.get("observationErrors"):
        return False
    if snapshot.get("backendOom") is True or snapshot.get("backendUnhealthy") is True:
        return False
    if snapshot.get("nodeComputeSaturated") is True or snapshot.get("nodeSchedulingPressure") is True:
        return False
    if snapshot.get("nodeScaleInProgress") is True or snapshot.get("caActivityActive") is True:
        return False
    if snapshot.get("albHealthy") is False or snapshot.get("albSaturated") is True:
        return False
    pods = snapshot.get("backendPods") if isinstance(snapshot.get("backendPods"), Mapping) else {}
    deployment = snapshot.get("deployment") if isinstance(snapshot.get("deployment"), Mapping) else {}
    hpa = snapshot.get("hpa") if isinstance(snapshot.get("hpa"), Mapping) else {}
    capacity = snapshot.get("capacity") if isinstance(snapshot.get("capacity"), Mapping) else {}
    if pods.get("pendingCount") != 0 or pods.get("restartCount") != 0:
        return False
    ready = _number(deployment.get("readyReplicas"))
    available = _number(deployment.get("availableReplicas"))
    desired = _number(deployment.get("desiredReplicas"))
    unavailable = _number(deployment.get("unavailableReplicas"))
    if None in (ready, available, desired) or ready != available or ready != desired or (unavailable or 0) != 0:
        return False
    hpa_desired = _number(hpa.get("desiredReplicas"))
    hpa_current = _number(hpa.get("currentReplicas"))
    if hpa_desired is None or hpa_current is None or hpa_desired != hpa_current or hpa_desired != ready:
        return False
    node_count = _number(snapshot.get("nodeCount"))
    ready_nodes = _number(snapshot.get("nodeReadyCount"))
    if node_count is None or ready_nodes is None or node_count != ready_nodes:
        return False
    if snapshot.get("capacityHealthy") is not True or capacity.get("healthy") is False:
        return False
    capacity_desired = _number(capacity.get("desired"))
    if capacity_desired is not None and capacity_desired != ready_nodes:
        return False
    # Every row must carry identity and no object may be in deletion/termination.
    identity_rows = list(_identity_rows(snapshot))
    if not identity_rows:
        return False
    for row in identity_rows:
        if not row.get("uid") and not row.get("podUid") and not row.get("nodeUid"):
            return False
        if row.get("deletionTimestamp") or row.get("terminating") is True or row.get("ready") is False:
            return False
    if snapshot.get("sloWindowComplete") is not True or snapshot.get("sloBreached") is True:
        return False
    if snapshot.get("runnerValid") is False:
        return False
    target = _number(snapshot.get("targetRps") or snapshot.get("targetRate")) or target_rate
    achieved = _number(snapshot.get("achievedRps"))
    if target is None or achieved is None or achieved < target * 0.9:
        return False
    return True


def _valid_windows(stage: Path) -> list[dict[str, Any]]:
    windows = read_jsonl(stage / "slo-windows.jsonl")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in windows:
        if row.get("sloWindowComplete") is not True or row.get("sloBreached") is True:
            continue
        # The producer's canonical SLO record uses the explicit ``sloWindow*``
        # names; older rehearsal fixtures used the shorter aliases. Accept
        # both representations so a completed adaptive stage is not treated
        # as window-less solely because the continuity reader lagged the
        # producer schema.
        key = str(
            row.get("sloWindowId")
            or row.get("windowId")
            or row.get("sloWindowStartUtc")
            or row.get("windowStartUtc")
            or row.get("startUtc")
            or ""
        )
        ts = parse_time(
            row.get("sloWindowEndUtc")
            or row.get("windowEndUtc")
            or row.get("endUtc")
            or row.get("ts")
        )
        if not key or ts is None or key in seen:
            continue
        seen.add(key)
        result.append({"id": key, "ts": ts})
    return sorted(result, key=lambda row: row["ts"])


def evaluate(
    stage: Path,
    *,
    next_rate: int | None = None,
    now: float | None = None,
    stable_window_seconds: int = 60,
    required_windows: int = 2,
    max_observation_age_seconds: int = 60,
    max_observation_gap_seconds: int = 60,
    fast_handoff_gap_seconds: int = 10,
) -> dict[str, Any]:
    metadata = read_json(stage / "metadata.json")
    snapshots = read_jsonl(stage / "snapshots.jsonl")
    snapshots = sorted(
        (row for row in snapshots if parse_time(row.get("ts") or row.get("timestamp")) is not None),
        key=lambda row: parse_time(row.get("ts") or row.get("timestamp")) or 0,
    )
    result: dict[str, Any] = {
        "schemaVersion": "scrum80-stage-continuity/v1",
        "checkedAtUtc": utc_now(),
        "stage": str(stage),
        "nextRate": next_rate,
        "decision": "BLOCK",
        "restoreRate": None,
        "reasonCodes": [],
        "snapshotCount": len(snapshots),
        "windowCount": 0,
    }
    if not stage.is_dir() or not metadata or not snapshots:
        result["reasonCodes"].append("EVIDENCE_MISSING")
        return result
    now_value = now if now is not None else datetime.now(timezone.utc).timestamp()
    times = [parse_time(row.get("ts") or row.get("timestamp")) for row in snapshots]
    latest = times[-1]
    if latest is None or now_value - latest > max_observation_age_seconds:
        result["reasonCodes"].append("OBSERVATION_STALE")
    gaps = [right - left for left, right in zip(times, times[1:]) if left is not None and right is not None]
    if any(gap > max_observation_gap_seconds for gap in gaps):
        result["reasonCodes"].append("OBSERVATION_GAP")
    inputs = metadata.get("effectiveInputs") if isinstance(metadata.get("effectiveInputs"), Mapping) else {}
    metadata_rate = _number(metadata.get("rate") or inputs.get("baseRate"))
    stable = [row for row in snapshots if _stable_snapshot(row, metadata_rate)]
    if stable:
        stable_times = [parse_time(row.get("ts") or row.get("timestamp")) for row in stable]
        stable_times = [value for value in stable_times if value is not None]
        if not stable_times or stable_times[-1] - stable_times[0] < stable_window_seconds * required_windows:
            result["reasonCodes"].append("STABLE_DURATION_SHORT")
    else:
        result["reasonCodes"].append("HEALTHY_WINDOW_MISSING")
    fingerprints = {
        tuple(sorted(
            str(item.get("uid") or item.get("podUid") or item.get("nodeUid"))
            for item in _identity_rows(row)
        ))
        for row in stable
    }
    if len(fingerprints) > 1:
        result["reasonCodes"].append("IDENTITY_CHANGED")
    windows = _valid_windows(stage)
    result["windowCount"] = len(windows)
    result["windowIds"] = [row["id"] for row in windows]
    if len(windows) < required_windows or (len(windows) >= required_windows and windows[-1]["ts"] - windows[-required_windows]["ts"] < stable_window_seconds):
        result["reasonCodes"].append("COMPLETE_WINDOWS_MISSING")
    # A prior segment may have reached a larger capacity and then been
    # replaced/terminated.  Equal counts are not enough; a decrease or a
    # workload signal means a high-rate dispatch must first restore low.
    latest_row = snapshots[-1]
    latest_nodes = _number(latest_row.get("nodeReadyCount"))
    latest_pods = _number((latest_row.get("backendPods") or {}).get("readyCount")) if isinstance(latest_row.get("backendPods"), Mapping) else None
    max_nodes = max((_number(row.get("nodeReadyCount")) or 0 for row in snapshots), default=0)
    max_pods = max((_number((row.get("backendPods") or {}).get("readyCount")) or 0 for row in snapshots if isinstance(row.get("backendPods"), Mapping)), default=0)
    status = read_json(stage / "run-status.json")
    controller = read_json(stage / "controller-result.json")
    if (latest_nodes is not None and latest_nodes < max_nodes) or (latest_pods is not None and latest_pods < max_pods):
        result["reasonCodes"].append("CAPACITY_DROPPED")
    # The adaptive coordinator deliberately signals the workload at a clean
    # stage boundary so it can flush and seal the segment.  That expected
    # signal is safe only when the controller explicitly records the boundary;
    # an unmarked signal remains an interrupted segment and forces restore-low.
    expected_boundary = controller.get("intentionalStageBoundary") is True and controller.get("terminalReason") == "STAGE_COMPLETE"
    if (status.get("workloadSignalReceived") is True and not expected_boundary) or controller.get("terminalReason") not in {"STAGE_COMPLETE", None}:
        result["reasonCodes"].append("INTERRUPTED_SEGMENT")
    if not metadata.get("actualOperationStartAtUtc") and not status.get("actualOperationStartAtUtc"):
        result["reasonCodes"].append("ACTUAL_OPERATION_START_MISSING")
    if result["reasonCodes"]:
        restore_reasons = {"CAPACITY_DROPPED", "INTERRUPTED_SEGMENT", "ACTUAL_OPERATION_START_MISSING"}
        result["decision"] = "RESTORE_LOW" if restore_reasons.intersection(result["reasonCodes"]) else "BLOCK"
        if result["decision"] == "RESTORE_LOW":
            result["restoreRate"] = int(metadata.get("rate") or metadata.get("effectiveInputs", {}).get("baseRate") or 0) or None
        return result
    result["decision"] = "ALLOW"
    result["reasonCodes"] = ["TWO_HEALTHY_WINDOWS", "STABLE_IDENTITY", "FRESH_OBSERVATIONS"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-stage", required=True, type=Path)
    parser.add_argument("--next-rate", type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--now-utc")
    parser.add_argument("--stable-window-seconds", type=int, default=60)
    parser.add_argument("--required-windows", type=int, default=2)
    parser.add_argument("--max-observation-age-seconds", type=int, default=60)
    parser.add_argument("--max-observation-gap-seconds", type=int, default=60)
    parser.add_argument("--fast-handoff-gap-seconds", type=int, default=10)
    args = parser.parse_args(argv)
    now = parse_time(args.now_utc) if args.now_utc else None
    if args.now_utc and now is None:
        parser.error("--now-utc must be an ISO-8601 UTC timestamp")
    verdict = evaluate(
        args.previous_stage,
        next_rate=args.next_rate,
        now=now,
        stable_window_seconds=args.stable_window_seconds,
        required_windows=args.required_windows,
        max_observation_age_seconds=args.max_observation_age_seconds,
        max_observation_gap_seconds=args.max_observation_gap_seconds,
        fast_handoff_gap_seconds=args.fast_handoff_gap_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": verdict["decision"], "reasonCodes": verdict["reasonCodes"]}, sort_keys=True))
    return {"ALLOW": ALLOW, "RESTORE_LOW": RESTORE_LOW, "BLOCK": BLOCK}[verdict["decision"]]


if __name__ == "__main__":
    raise SystemExit(main())
