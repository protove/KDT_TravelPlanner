#!/usr/bin/env python3
"""Export fixed-range Grafana and recovery evidence for one AWS Recovery run.

The exporter is intentionally read-only.  It never performs an ASG action,
Terraform operation, or rollback.  It validates the T0--T6 event contract and
the restoration invariant before collecting Grafana material, so a partial or
unscoped evidence bundle cannot be mistaken for a completed experiment.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECOVERY_RUN_ID = re.compile(r"^aws-(?:recovery|b02|r01|r03|r05|r07)-[A-Za-z0-9._-]+$")
COMPARISON_RUN_ID = re.compile(r"^scrum43-(?:b02|r01|r03|r05|r07)-[A-Za-z0-9._-]+$")
REQUIRED_EVENTS = ("RUN_START", "T0", "T1", "T2", "T3", "T4", "T5", "T6", "RUN_END")
DEFAULT_EMPTY_IS_VALID = {"http_5xx", "loki_warn_error", "aws_asg_activities_empty"}


class RecoveryExportError(RuntimeError):
    """A sanitized, fail-closed recovery evidence error."""


def _load_grafana_exporter():
    path = Path(__file__).with_name("export-grafana-evidence.py")
    spec = importlib.util.spec_from_file_location("export_grafana_evidence", path)
    if not spec or not spec.loader:
        raise RecoveryExportError("unable to load shared Grafana exporter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError) as error:
        raise RecoveryExportError("operations.jsonl contains an invalid UTC timestamp") from error


def iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryExportError(f"invalid JSON evidence: {path.name}") from error
    if not isinstance(payload, dict):
        raise RecoveryExportError(f"JSON object expected: {path.name}")
    return payload


def resolve_run(root: Path, run_id: str) -> tuple[str, str, str]:
    if not RECOVERY_RUN_ID.fullmatch(run_id):
        raise RecoveryExportError("--run-id must use an approved Recovery prefix")
    metadata = read_json(root / "metadata.json")
    if metadata.get("runId") != run_id or metadata.get("scenarioId") != "AWS-RECOVERY":
        raise RecoveryExportError("metadata runId/scenarioId does not match this Recovery export")
    started = metadata.get("startedAtUtc")
    ended = metadata.get("endedAtUtc")
    if not isinstance(started, str) or not isinstance(ended, str) or not started or not ended:
        raise RecoveryExportError("metadata must contain a closed startedAtUtc/endedAtUtc range")
    parse_timestamp(started)
    parse_timestamp(ended)
    if parse_timestamp(ended) <= parse_timestamp(started):
        raise RecoveryExportError("Recovery UTC range must be positive")
    return run_id, started, ended


def read_recovery_events(path: Path, *, require_all: bool = True) -> dict[str, float]:
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryExportError("operations.jsonl is missing or invalid") from error
    events: dict[str, float] = {}
    physical: list[str] = []
    for record in records:
        event = record.get("event")
        if event not in REQUIRED_EVENTS:
            continue
        if event in events:
            raise RecoveryExportError(f"duplicate recovery event: {event}")
        ts = record.get("ts")
        if not isinstance(ts, str):
            raise RecoveryExportError(f"recovery event has no timestamp: {event}")
        events[event] = parse_timestamp(ts)
        physical.append(event)
    missing = [event for event in REQUIRED_EVENTS if event not in events]
    if require_all and missing:
        raise RecoveryExportError("missing recovery events: " + ",".join(missing))
    if not require_all:
        # A FAILED/INVALID run may legally stop early, but what was recorded
        # must still be a strictly-ordered prefix of the event contract plus
        # the mandatory RUN_START/RUN_END boundaries.
        if "RUN_START" not in events or "RUN_END" not in events:
            raise RecoveryExportError("missing recovery events: RUN_START/RUN_END")
        middle_contract = [event for event in REQUIRED_EVENTS if event not in ("RUN_START", "RUN_END")]
        recorded_middle = [event for event in middle_contract if event in events]
        if recorded_middle != middle_contract[: len(recorded_middle)]:
            raise RecoveryExportError("failed-run events are not a prefix of the T0-T6 contract")
    expected_physical = [event for event in REQUIRED_EVENTS if event in events]
    if physical != expected_physical:
        raise RecoveryExportError("T0-T6 events are not in the required physical order")
    timestamps = [events[event] for event in REQUIRED_EVENTS if event in events]
    if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
        raise RecoveryExportError("T0-T6 event timestamps are not strictly chronological")
    return events


def build_recovery_timing(events: dict[str, float]) -> dict[str, Any]:
    def span(start: str, end: str) -> float | None:
        if start in events and end in events:
            return round(events[end] - events[start], 3)
        return None

    complete = all(event in events for event in REQUIRED_EVENTS)
    timing: dict[str, Any] = {"status": "collected" if complete else "partial"}
    for event in REQUIRED_EVENTS:
        if event in ("RUN_START", "RUN_END"):
            continue
        if event in events:
            timing[event] = iso_timestamp(events[event])
    timing.update(
        {
            "detectorToRollbackSeconds": span("T3", "T4"),
            "rollbackToHealthySeconds": span("T4", "T5"),
            "healthyToSloSeconds": span("T5", "T6"),
            "T1ToT6Seconds": span("T1", "T6"),
            "T4ToT6Seconds": span("T4", "T6"),
            "source": "operations.jsonl",
        }
    )
    return timing


def validate_required_metrics(
    payload: dict[str, Any],
    required: list[str],
    empty_is_valid: set[str] | None = None,
) -> dict[str, Any]:
    empty_is_valid = empty_is_valid or set()
    raw = payload.get("metrics")
    if isinstance(raw, list):
        metrics = {item.get("name"): item for item in raw if isinstance(item, dict) and item.get("name")}
    elif isinstance(raw, dict):
        metrics = raw
    else:
        raise RecoveryExportError("monitoring/required-metrics.json has no metrics object/list")
    missing: list[str] = []
    failed: list[str] = []
    empty_validated: list[str] = []
    for name in required:
        item = metrics.get(name)
        if not isinstance(item, dict) or item.get("status") != "collected":
            missing.append(name)
            continue
        try:
            count = int(item.get("datapointCount", 0))
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            if name in empty_is_valid or item.get("emptyIsValid") is True:
                empty_validated.append(name)
            else:
                failed.append(name)
    status = "collected" if not missing and not failed else "INVALID_OBSERVABILITY_EVIDENCE"
    return {
        "status": status,
        "required": required,
        "missing": missing,
        "emptyRequired": failed,
        "emptyIsValid": empty_validated,
        "collectedCount": len(required) - len(missing) - len(failed),
    }


def validate_restoration_invariant(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    required = {
        "status", "desiredCapacity", "minSize", "maxSize", "launchTemplateVersion",
        "normalImageDigest", "capacityRestored", "scalingPolicyEnabled",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RecoveryExportError("restoration-state.json is missing: " + ",".join(missing))
    if payload.get("status") != "verified" or payload.get("capacityRestored") is not True:
        raise RecoveryExportError("restoration invariant is not verified")
    if payload.get("scalingPolicyEnabled") is not True:
        raise RecoveryExportError("restoration invariant requires scaling policy enabled")
    if not isinstance(payload.get("normalImageDigest"), str) or not re.search(r"@sha256:[0-9a-f]{64}$", payload["normalImageDigest"]):
        raise RecoveryExportError("restoration invariant requires a digest-pinned normal image")
    if not re.fullmatch(r"[0-9]+", str(payload.get("launchTemplateVersion"))):
        raise RecoveryExportError("restoration invariant requires a numbered Launch Template version")
    if any(not isinstance(payload.get(field), int) or payload[field] < 0 for field in ("desiredCapacity", "minSize", "maxSize")):
        raise RecoveryExportError("restoration capacity fields must be non-negative integers")
    return {
        "status": "verified",
        "desiredCapacity": payload["desiredCapacity"],
        "minSize": payload["minSize"],
        "maxSize": payload["maxSize"],
        "launchTemplateVersion": str(payload["launchTemplateVersion"]),
        "normalImageDigest": payload["normalImageDigest"],
        "capacityRestored": True,
        "scalingPolicyEnabled": True,
        "source": "aws/restoration-state.json",
    }


def validate_verdict(path: Path, run_id: str) -> dict[str, Any]:
    """Require the pure evaluator's verdict before exporting derived evidence.

    PASSED verdicts must carry the full T0-T6 timeline. FAILED and INVALID
    verdicts are preserved and exported too — a run that missed the SLO is
    still evidence — but they must carry the sanitized failure fields instead.
    """

    payload = read_json(path)
    if payload.get("runId") != run_id or payload.get("scenarioId") != "AWS-RECOVERY":
        raise RecoveryExportError("recovery-verdict.json is bound to a different Recovery run")
    status = payload.get("status")
    if status not in {"PASSED", "FAILED", "INVALID_RUN", "INVALID_OBSERVABILITY_EVIDENCE"}:
        raise RecoveryExportError("recovery-verdict.json has an unsupported status")
    if status == "PASSED":
        for field in ("T0", "T1", "T2", "T3", "T4", "T5", "T6", "RUN_END"):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise RecoveryExportError(f"recovery-verdict.json is missing {field}")
    else:
        for field in ("errorType", "detail"):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise RecoveryExportError(f"non-passed recovery-verdict.json is missing {field}")
    return {
        "status": status,
        "runId": run_id,
        "sloVersion": payload.get("sloVersion"),
        "T1ToT6Seconds": payload.get("T1ToT6Seconds"),
        "T4ToT6Seconds": payload.get("T4ToT6Seconds"),
        **(
            {}
            if status == "PASSED"
            else {"errorType": payload.get("errorType"), "detail": payload.get("detail")}
        ),
        "source": "recovery-verdict.json",
    }


def resolve_comparison_run(root: Path, run_id: str) -> tuple[str, str, str]:
    """Resolve a v1.1 comparison run without accepting legacy metadata."""
    if not COMPARISON_RUN_ID.fullmatch(run_id):
        raise RecoveryExportError("--run-id must use an approved scrum43 comparison prefix")
    metadata = read_json(root / "metadata.json")
    if metadata.get("runId") != run_id or metadata.get("scenarioId") != "AWS-RECOVERY-COMPARISON":
        raise RecoveryExportError("metadata runId/scenarioId does not match comparison Recovery export")
    started = metadata.get("startedAtUtc")
    ended = metadata.get("endedAtUtc")
    if not isinstance(started, str) or not isinstance(ended, str) or not started or not ended:
        raise RecoveryExportError("comparison metadata must contain a closed UTC range")
    parse_timestamp(started)
    parse_timestamp(ended)
    if parse_timestamp(ended) <= parse_timestamp(started):
        raise RecoveryExportError("comparison UTC range must be positive")
    return run_id, started, ended


def validate_comparison_verdict(path: Path, run_id: str) -> dict[str, Any]:
    """Validate the independent v1.1 evaluator output, including no-T6 failures."""
    payload = read_json(path)
    if payload.get("runId") != run_id or payload.get("scenarioId") != "AWS-RECOVERY-COMPARISON":
        raise RecoveryExportError("comparison recovery-verdict.json is bound to a different run")
    status = payload.get("status")
    if status not in {"PASSED", "VALID_EXPERIMENTAL_FAILURE", "INVALID_RUN"}:
        raise RecoveryExportError("comparison recovery-verdict.json has an unsupported status")
    if status == "PASSED":
        required = ("T0", "T1", "T2", "T3", "T4", "T5", "T6", "RUN_END")
        for field in required:
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise RecoveryExportError(f"comparison recovery-verdict.json is missing {field}")
    else:
        for field in ("errorType", "detail"):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise RecoveryExportError(f"comparison non-passed verdict is missing {field}")
    return {
        "status": status,
        "runId": run_id,
        "scenarioId": "AWS-RECOVERY-COMPARISON",
        "scenario": payload.get("scenario"),
        "platform": payload.get("platform"),
        "sloVersion": payload.get("sloVersion"),
        "T1ToT6Seconds": payload.get("T1ToT6Seconds"),
        "T4ToT6Seconds": payload.get("T4ToT6Seconds"),
        **(
            {}
            if status == "PASSED"
            else {"errorType": payload.get("errorType"), "detail": payload.get("detail")}
        ),
        "source": "recovery-verdict.json",
    }


def export_comparison_recovery_evidence(
    evidence_root: Path,
    run_id: str,
    grafana_url: str,
    user: str,
    password: str,
    region: str,
    dashboard_uid: str = "aws-recovery",
    anonymous_viewer: bool = False,
) -> dict[str, Any]:
    """Export a v1.1 comparison bundle while preserving valid no-T6 failures."""
    run_id, from_utc, to_utc = resolve_comparison_run(evidence_root, run_id)
    verdict = validate_comparison_verdict(evidence_root / "recovery-verdict.json", run_id)
    events = read_recovery_events(
        evidence_root / "operations.jsonl", require_all=verdict["status"] == "PASSED"
    )
    range_start = parse_timestamp(from_utc)
    range_end = parse_timestamp(to_utc)
    if any(value < range_start or value > range_end for value in events.values()):
        raise RecoveryExportError("comparison event falls outside metadata's fixed UTC range")

    profile_path = Path(__file__).parents[3] / "load-tests/aws/profiles/ec2-eks-recovery-v1.1.json"
    profile = read_json(profile_path)
    required = list(profile.get("observability", {}).get("required", []))
    metric_status = validate_required_metrics(
        read_json(evidence_root / "monitoring/required-metrics.json"), required,
        {"core_unexpected_errors_total", "core_contract_failures_total", "aws_target_health"},
    )
    if verdict["status"] == "PASSED" and metric_status["status"] != "collected":
        raise RecoveryExportError("comparison observability evidence is incomplete")

    platform_recovery_path = evidence_root / "control" / "restoration-readback.json"
    if not platform_recovery_path.is_file():
        platform_recovery_path = evidence_root / "restoration-readback.json"
    platform_recovery = read_json(platform_recovery_path) if platform_recovery_path.is_file() else {"status": "not-observed"}
    if verdict["status"] == "PASSED" and platform_recovery.get("status") not in {"verified", "restored"} and platform_recovery.get("deploymentReady") is not True:
        raise RecoveryExportError("comparison platform recovery readback is not verified")

    exporter = _load_grafana_exporter()
    if not exporter.is_loopback_grafana_url(grafana_url):
        raise RecoveryExportError("--grafana-url must be a loopback SSM port-forward endpoint")
    if anonymous_viewer:
        auth_header = None
    else:
        if not user or not password:
            raise RecoveryExportError("--user/--password are required unless --anonymous-viewer is used")
        auth_header = exporter.basic_auth_header(user, password)
    grafana_dir = evidence_root / "grafana"
    queries_dir = grafana_dir / "queries"
    panels_dir = grafana_dir / "panels"
    queries_dir.mkdir(parents=True, exist_ok=True)
    panels_dir.mkdir(parents=True, exist_ok=True)
    dashboard = exporter.fetch_dashboard(grafana_url, auth_header, dashboard_uid)
    (grafana_dir / "dashboard.json").write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
    dimensions = exporter.load_resource_dimensions(evidence_root)
    exporter.validate_resource_dimensions(dimensions)
    from_ms = exporter.to_epoch_seconds(from_utc) * 1000
    to_ms = exporter.to_epoch_seconds(to_utc) * 1000
    annotations = exporter.fetch_annotations(grafana_url, auth_header, run_id, from_ms, to_ms)
    (grafana_dir / "annotations.json").write_text(
        json.dumps({"runId": run_id, "fromUtc": from_utc, "toUtc": to_utc, "annotations": annotations}, indent=2) + "\n",
        encoding="utf-8",
    )
    queries = exporter.extract_panel_queries(dashboard, dimensions)
    collected, failed = exporter.collect_panel_queries(
        grafana_url, auth_header, queries, from_utc, to_utc, region, queries_dir,
    )
    contracts = exporter.build_panel_capture_contracts(
        dashboard, queries, grafana_url, run_id, from_utc, to_utc, dimensions,
    )
    exporter.write_panel_capture_contracts(contracts, panels_dir)
    dashboard_contract = exporter.build_dashboard_capture_contract(
        dashboard, grafana_url, run_id, from_utc, to_utc, dimensions,
    )
    (grafana_dir / "dashboard.capture.json").write_text(
        json.dumps(dashboard_contract, indent=2) + "\n", encoding="utf-8",
    )
    (panels_dir / "status.json").write_text(json.dumps({
        "status": "pending-manual-capture",
        "panelCount": len(contracts),
        "runId": run_id,
        "fromUtc": from_utc,
        "toUtc": to_utc,
        "dashboardCapture": dashboard_contract,
        "accessMode": "anonymous-viewer" if anonymous_viewer else "basic-auth",
        "reason": "D-003-R1 requires fixed panel and full-dashboard screenshots via SSM port-forward and browser.",
    }, indent=2) + "\n", encoding="utf-8")
    timing = build_recovery_timing(events)
    (evidence_root / "recovery-timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "recovery-observability.json").write_text(json.dumps(metric_status, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "recovery-restoration.json").write_text(json.dumps(platform_recovery, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "recovery-verdict-export.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    summary = {
        "status": "collected" if failed == 0 else "INVALID_OBSERVABILITY_EVIDENCE",
        "verdictStatus": verdict["status"],
        "runId": run_id,
        "scenarioId": "AWS-RECOVERY-COMPARISON",
        "fromUtc": from_utc,
        "toUtc": to_utc,
        "dashboardUid": dashboard.get("dashboard", {}).get("uid"),
        "dashboardVersion": dashboard.get("dashboard", {}).get("version"),
        "queryCount": len(queries),
        "queryCollected": collected,
        "queryFailed": failed,
        "panelCount": len(contracts),
        "dashboardCapturePath": "grafana/dashboard.capture.json",
        "expectedDashboardPngPath": "grafana/dashboard.png",
        "timingPath": "recovery-timing.json",
        "restorationPath": "recovery-restoration.json",
        "observabilityPath": "recovery-observability.json",
        "verdictPath": "recovery-verdict.json",
        "pngStatus": "pending-manual-capture",
        "accessMode": "anonymous-viewer" if anonymous_viewer else "basic-auth",
    }
    (evidence_root / "recovery-export-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8",
    )
    if failed:
        raise RecoveryExportError(f"{failed} Grafana queries failed; evidence is not complete")
    return summary


def export_recovery_evidence(
    evidence_root: Path,
    run_id: str,
    grafana_url: str,
    user: str,
    password: str,
    region: str,
    dashboard_uid: str = "aws-recovery",
    empty_is_valid: set[str] | None = None,
    anonymous_viewer: bool = False,
) -> dict[str, Any]:
    run_id, from_utc, to_utc = resolve_run(evidence_root, run_id)
    verdict = validate_verdict(evidence_root / "recovery-verdict.json", run_id)
    verdict_passed = verdict["status"] == "PASSED"
    events = read_recovery_events(
        evidence_root / "operations.jsonl", require_all=verdict_passed
    )
    range_start = parse_timestamp(from_utc)
    range_end = parse_timestamp(to_utc)
    if any(timestamp < range_start or timestamp > range_end for timestamp in events.values()):
        raise RecoveryExportError("T0-T6 event falls outside metadata's fixed UTC range")
    profile_path = Path(__file__).parents[3] / "load-tests/aws/profiles/ec2-recovery.json"
    profile = read_json(profile_path)
    required = list(profile.get("observability", {}).get("required", []))
    metric_status = validate_required_metrics(
        read_json(evidence_root / "monitoring/required-metrics.json"), required, empty_is_valid,
    )
    if verdict_passed and metric_status["status"] != "collected":
        raise RecoveryExportError("required observability evidence is incomplete")
    restoration = validate_restoration_invariant(evidence_root / "aws/restoration-state.json")

    exporter = _load_grafana_exporter()
    if not exporter.is_loopback_grafana_url(grafana_url):
        raise RecoveryExportError("--grafana-url must be a loopback SSM port-forward endpoint")
    if anonymous_viewer:
        auth_header = None
    else:
        if not user or not password:
            raise RecoveryExportError("--user/--password are required unless --anonymous-viewer is used")
        auth_header = exporter.basic_auth_header(user, password)
    grafana_dir = evidence_root / "grafana"
    queries_dir = grafana_dir / "queries"
    panels_dir = grafana_dir / "panels"
    queries_dir.mkdir(parents=True, exist_ok=True)
    panels_dir.mkdir(parents=True, exist_ok=True)
    dashboard = exporter.fetch_dashboard(grafana_url, auth_header, dashboard_uid)
    (grafana_dir / "dashboard.json").write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
    dimensions = exporter.load_resource_dimensions(evidence_root)
    exporter.validate_resource_dimensions(dimensions)
    from_ms = exporter.to_epoch_seconds(from_utc) * 1000
    to_ms = exporter.to_epoch_seconds(to_utc) * 1000
    annotations = exporter.fetch_annotations(grafana_url, auth_header, run_id, from_ms, to_ms)
    (grafana_dir / "annotations.json").write_text(json.dumps({"runId": run_id, "fromUtc": from_utc, "toUtc": to_utc, "annotations": annotations}, indent=2) + "\n", encoding="utf-8")
    queries = exporter.extract_panel_queries(dashboard, dimensions)
    collected, failed = exporter.collect_panel_queries(grafana_url, auth_header, queries, from_utc, to_utc, region, queries_dir)
    contracts = exporter.build_panel_capture_contracts(dashboard, queries, grafana_url, run_id, from_utc, to_utc, dimensions)
    exporter.write_panel_capture_contracts(contracts, panels_dir)
    dashboard_contract = exporter.build_dashboard_capture_contract(
        dashboard, grafana_url, run_id, from_utc, to_utc, dimensions,
    )
    (grafana_dir / "dashboard.capture.json").write_text(
        json.dumps(dashboard_contract, indent=2) + "\n", encoding="utf-8",
    )
    (panels_dir / "status.json").write_text(json.dumps({
        "status": "pending-manual-capture",
        "panelCount": len(contracts),
        "runId": run_id,
        "fromUtc": from_utc,
        "toUtc": to_utc,
        "dashboardCapture": dashboard_contract,
        "accessMode": "anonymous-viewer" if anonymous_viewer else "basic-auth",
        "reason": "D-003-R1 requires fixed Panel ID screenshots via SSM port-forward and browser.",
    }, indent=2) + "\n", encoding="utf-8")
    timing = build_recovery_timing(events)
    (evidence_root / "recovery-timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "recovery-observability.json").write_text(json.dumps(metric_status, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "recovery-restoration.json").write_text(json.dumps(restoration, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "recovery-verdict-export.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    summary = {
        "status": "collected" if failed == 0 else "INVALID_OBSERVABILITY_EVIDENCE",
        "verdictStatus": verdict["status"],
        "runId": run_id,
        "scenarioId": "AWS-RECOVERY",
        "fromUtc": from_utc,
        "toUtc": to_utc,
        "dashboardUid": dashboard.get("dashboard", {}).get("uid"),
        "dashboardVersion": dashboard.get("dashboard", {}).get("version"),
        "queryCount": len(queries),
        "queryCollected": collected,
        "queryFailed": failed,
        "panelCount": len(contracts),
        "dashboardCapturePath": "grafana/dashboard.capture.json",
        "expectedDashboardPngPath": "grafana/dashboard.png",
        "timingPath": "recovery-timing.json",
        "restorationPath": "recovery-restoration.json",
        "observabilityPath": "recovery-observability.json",
        "verdictPath": "recovery-verdict.json",
        "pngStatus": "pending-manual-capture",
        "accessMode": "anonymous-viewer" if anonymous_viewer else "basic-auth",
    }
    (evidence_root / "recovery-export-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if failed:
        raise RecoveryExportError(f"{failed} Grafana queries failed; evidence is not complete")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--grafana-url", required=True)
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--region", required=True)
    parser.add_argument("--dashboard-uid", default="aws-recovery")
    parser.add_argument("--empty-is-valid-metric", action="append", default=[])
    parser.add_argument(
        "--anonymous-viewer",
        action="store_true",
        help="Use explicit action-time anonymous Viewer access over a loopback SSM tunnel (default: basic auth).",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.evidence_root.resolve()
    if not root.is_dir():
        raise RecoveryExportError("--evidence-root does not exist")
    metadata = read_json(root / "metadata.json")
    comparison = metadata.get("scenarioId") == "AWS-RECOVERY-COMPARISON" or COMPARISON_RUN_ID.fullmatch(args.run_id)
    if comparison:
        run_id, from_utc, to_utc = resolve_comparison_run(root, args.run_id)
    else:
        run_id, from_utc, to_utc = resolve_run(root, args.run_id)
    events = read_recovery_events(root / "operations.jsonl", require_all=not comparison)
    if args.dry_run:
        print(f"[recovery-export] dry-run run={run_id} range={from_utc}..{to_utc} dashboard={args.dashboard_uid} events={len(events)}")
        return 0
    if comparison:
        result = export_comparison_recovery_evidence(
            root, run_id, args.grafana_url, args.user, args.password, args.region,
            args.dashboard_uid, args.anonymous_viewer,
        )
    else:
        result = export_recovery_evidence(
            root, run_id, args.grafana_url, args.user, args.password, args.region,
            args.dashboard_uid, DEFAULT_EMPTY_IS_VALID | set(args.empty_is_valid_metric),
            args.anonymous_viewer,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecoveryExportError as error:
        print(f"[recovery-export] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
