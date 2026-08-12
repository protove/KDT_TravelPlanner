#!/usr/bin/env python3
"""Validate a completed AWS B-01 evidence bundle and emit a sanitized gate
report, per aws-load-test-handoff/contracts/SLO_AND_METRIC_CONTRACT.md and
EVIDENCE_BUNDLE_CONTRACT.md.

This is a standalone follow-up step, not something orchestrate-aws-b01.sh
calls internally — mirroring how ../summarize-gate.py is a separate
Compose-side tool the operator (or CI) runs against a completed gate
manifest, not something run-compose-gate.py invokes itself.

Why this recomputes core_* counts from raw.json instead of trusting
summary.json's aggregate counters directly: SLO_AND_METRIC_CONTRACT.md
requires excluding warm-up from the Baseline measurement window ("정상 성공
처리율은 warm-up을 제외한 10분 Baseline 전체 창에서 계산한다"), but
load-tests/k6/aws/scenarios/b01-baseline.js runs warm-up and the measured
window as one constant-arrival-rate k6 scenario (same executor, same rate,
no phase boundary inside k6 itself) — see that file's totalDuration(). Its
handleSummary() therefore aggregates the whole run, warm-up included. This
script instead reads the individual core_*_total Point entries k6 writes to
raw.json (one per Counter.add() call, each carrying its own timestamp) and
only counts the ones at or after RUN_START + warmupSeconds, the same
"filter raw Points by a timestamp boundary" technique
../evaluate-recovery.py already uses for Compose recovery windows.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SAFETY_SCRIPT = REPOSITORY_ROOT / "scripts/loadtest/verify-evidence-safety.py"

P95_MS = 500.0
UNEXPECTED_ERROR_RATE = 0.01
CONTRACT_FAILURE_RATE = 0.01
SUCCESS_RATE_FLOOR = 0.99
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CORE_COUNTERS = (
    "core_operations_total",
    "core_completed_operations_total",
    "core_successful_operations_total",
    "core_unexpected_errors_total",
    "core_contract_failures_total",
)
ASSESSED_PHASES = ("smoke", "ramp", "baseline-1", "baseline-2", "baseline-3", "spike")
TIMELINE_ITEMS_PER_PLANNER = 3


class ValidationError(RuntimeError):
    """A sanitized, structural evidence-bundle problem (not an SLO miss)."""


def load_safety_module():
    spec = importlib.util.spec_from_file_location("verify_evidence_safety", SAFETY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict:
    if not path.exists():
        raise ValidationError(f"missing required evidence file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid JSON in {path}: {error}") from error


def timestamp(value: str) -> float:
    # k6 may emit nanosecond precision while Python's stdlib accepts at most
    # microseconds in fromisoformat(). Truncate excess fractional precision
    # only; keep the timezone marker intact.
    match = re.fullmatch(r"(.+\.)(\d+)(Z|[+-]\d{2}:\d{2})", value)
    if match:
        value = f"{match.group(1)}{match.group(2)[:6].ljust(6, '0')}{match.group(3)}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile_value
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def read_run_start(run_dir: Path) -> float | None:
    operations_path = run_dir / "operations.jsonl"
    if not operations_path.exists():
        return None
    for line in operations_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("event") == "RUN_START":
            return timestamp(entry["ts"])
    return None


def core_counts_since(raw_path: Path, since_ts: float | None) -> dict:
    counts = {name: 0 for name in CORE_COUNTERS}
    durations: list[float] = []
    if not raw_path.exists():
        return {"counts": counts, "durations": durations}
    with raw_path.open(encoding="utf-8") as source:
        for raw_line in source:
            try:
                point = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if point.get("type") != "Point" or "data" not in point:
                continue
            data = point["data"]
            metric = point.get("metric")
            if metric not in CORE_COUNTERS and metric != "http_req_duration":
                continue
            try:
                point_ts = timestamp(data["time"])
            except (KeyError, ValueError):
                continue
            if since_ts is not None and point_ts < since_ts:
                continue
            if metric in CORE_COUNTERS:
                counts[metric] += int(data.get("value", 0))
            elif metric == "http_req_duration":
                durations.append(float(data["value"]))
    return {"counts": counts, "durations": durations}


def runner_stats(run_dir: Path) -> dict:
    stats_path = run_dir / "runner-stats.jsonl"
    if not stats_path.exists():
        return {"samples": 0, "maxCpuPercent": None, "maxMemoryPercent": None}
    cpu_values: list[float] = []
    memory_values: list[float] = []
    samples = 0
    percent_pattern = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?)%\s*")
    for line in stats_path.read_text(encoding="utf-8").splitlines():
        try:
            docker = json.loads(line).get("docker", {})
        except json.JSONDecodeError:
            continue
        if not isinstance(docker, dict):
            continue
        samples += 1
        cpu_match = percent_pattern.fullmatch(docker.get("CPUPerc", "") or "")
        memory_match = percent_pattern.fullmatch(docker.get("MemPerc", "") or "")
        if cpu_match:
            cpu_values.append(float(cpu_match.group(1)))
        if memory_match:
            memory_values.append(float(memory_match.group(1)))
    return {
        "samples": samples,
        "maxCpuPercent": max(cpu_values) if cpu_values else None,
        "maxMemoryPercent": max(memory_values) if memory_values else None,
    }


# D-001-R1 (aws-load-test-handoff/decisions/DECISION_LOG.md): t3.small is the
# default Runner candidate, re-tested with t3.medium only once Runner-side
# CPU/memory/OOM/restart evidence shows a bottleneck. These thresholds are
# what "shows a bottleneck" means operationally — a run this hot on the
# Runner side should not be read as a SUT/backend SLO miss.
RUNNER_BOTTLENECK_CPU_PERCENT = 90.0
RUNNER_BOTTLENECK_MEMORY_PERCENT = 90.0


def runner_bottleneck_suspected(stats: dict, oom_killed: bool, restart_count: int) -> bool:
    if oom_killed or restart_count > 0:
        return True
    if stats["maxCpuPercent"] is not None and stats["maxCpuPercent"] >= RUNNER_BOTTLENECK_CPU_PERCENT:
        return True
    if stats["maxMemoryPercent"] is not None and stats["maxMemoryPercent"] >= RUNNER_BOTTLENECK_MEMORY_PERCENT:
        return True
    return False


def evaluate_phase(run_dir: Path) -> dict:
    metadata = read_json(run_dir / "metadata.json")
    status = read_json(run_dir / "run-status.json")
    summary = read_json(run_dir / "summary.json")
    warmup_seconds = int(metadata.get("warmupSeconds") or 0)
    run_start = read_run_start(run_dir)
    since_ts = (run_start + warmup_seconds) if (run_start is not None and warmup_seconds > 0) else None

    raw_result = core_counts_since(run_dir / "raw.json", since_ts)
    counts = raw_result["counts"]
    completed = counts["core_completed_operations_total"]
    successful = counts["core_successful_operations_total"]
    unexpected = counts["core_unexpected_errors_total"]
    contract_failures = counts["core_contract_failures_total"]
    success_rate = successful / completed if completed else None
    unexpected_error_rate = unexpected / completed if completed else None
    contract_failure_rate = contract_failures / completed if completed else None
    p95_ms = percentile(raw_result["durations"], 0.95)

    dropped_iterations = summary.get("metrics", {}).get("dropped_iterations", {}).get("count", 0)
    k6_exit_code = status.get("k6ExitCode")
    oom_killed = bool(status.get("k6ContainerOomKilled", False))
    restart_count = int(status.get("k6ContainerRestartCount", 0))
    stats = runner_stats(run_dir)
    bottleneck_suspected = runner_bottleneck_suspected(stats, oom_killed, restart_count)

    slo_pass = (
        k6_exit_code == 0
        and dropped_iterations == 0
        and completed > 0
        and p95_ms is not None and p95_ms <= P95_MS
        and success_rate is not None and success_rate >= SUCCESS_RATE_FLOOR
        and unexpected_error_rate is not None and unexpected_error_rate < UNEXPECTED_ERROR_RATE
        and contract_failure_rate is not None and contract_failure_rate < CONTRACT_FAILURE_RATE
        and not bottleneck_suspected
    )

    return {
        "directory": str(run_dir),
        "runId": metadata.get("runId"),
        "rate": metadata.get("rate"),
        "warmupSeconds": warmup_seconds,
        "excludedWarmupFromCoreCounts": since_ts is not None,
        "k6ExitCode": k6_exit_code,
        "k6ContainerOomKilled": oom_killed,
        "k6ContainerRestartCount": restart_count,
        "droppedIterations": dropped_iterations,
        "coreCounts": counts,
        "p95Ms": p95_ms,
        "successRate": round(success_rate, 4) if success_rate is not None else None,
        "unexpectedErrorRate": round(unexpected_error_rate, 4) if unexpected_error_rate is not None else None,
        "contractFailureRate": round(contract_failure_rate, 4) if contract_failure_rate is not None else None,
        "runnerStats": stats,
        # True means this run's failure (if any) should be attributed to the
        # Runner (retest at a bigger instance_type), not read as evidence
        # that the SUT/backend itself missed SLO.
        "runnerBottleneckSuspected": bottleneck_suspected,
        "sloPass": slo_pass,
    }


def discover_phases(evidence_root: Path) -> dict:
    k6_root = evidence_root / "k6"
    phases: dict = {"smoke": None, "ramp": None, "baseline": [], "spike": None}
    if not k6_root.is_dir():
        return phases
    for entry in sorted(k6_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == "smoke":
            phases["smoke"] = evaluate_phase(entry)
        elif entry.name == "ramp":
            phases["ramp"] = evaluate_phase(entry)
        elif entry.name == "spike":
            phases["spike"] = evaluate_phase(entry)
        elif entry.name.startswith("baseline"):
            phases["baseline"].append(evaluate_phase(entry))
    return phases


def evaluate_baseline_candidate(
    reps: list[dict],
    confirmed_rate: float | None,
    *,
    digest_gate_passed: bool = True,
) -> dict:
    numeric_rates: list[float] = []
    for rep in reps:
        value = rep.get("rate")
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            numeric_rates.append(numeric)
    rates = set(numeric_rates)
    all_rates_positive = len(numeric_rates) == len(reps) and all(rate > 0 for rate in numeric_rates)
    consistent_rate = len(reps) == 3 and all_rates_positive and len(rates) == 1
    if len(rates) == 1:
        candidate_rate = next(iter(rates))
    elif rates:
        candidate_rate = sorted(rates)
    else:
        candidate_rate = None
    try:
        numeric_confirmed_rate = float(confirmed_rate) if confirmed_rate is not None else None
    except (TypeError, ValueError):
        numeric_confirmed_rate = None
    confirmed_rate_valid = (
        numeric_confirmed_rate is not None
        and math.isfinite(numeric_confirmed_rate)
        and numeric_confirmed_rate > 0
    )
    rate_matches_confirmed = (
        confirmed_rate_valid
        and consistent_rate
        and candidate_rate == numeric_confirmed_rate
    )
    reps_passed = sum(1 for rep in reps if rep["sloPass"])
    return {
        "repsCount": len(reps),
        "repsPassed": reps_passed,
        "rate": candidate_rate,
        "rateConsistentAcrossReps": consistent_rate,
        "allRatesPositive": all_rates_positive,
        "confirmedRateProvided": confirmed_rate is not None,
        "confirmedRateValid": confirmed_rate_valid,
        "rateMatchesConfirmedRate": rate_matches_confirmed,
        # D-005: "3회 중 하나라도 99% 미만이면 해당 arrival-rate 후보를 동결하지 않는다"
        # The operator-confirmed rate is part of the gate, rather than an
        # optional display-only comparison. This prevents a candidate with
        # missing metadata or a different CLI rate from being frozen.
        "frozen": (
            len(reps) == 3
            and reps_passed == 3
            and consistent_rate
            and rate_matches_confirmed
            and digest_gate_passed
        ),
    }


def evaluate_baseline_candidate_only(evidence_root: Path, confirmed_rate: float | None) -> dict:
    """Evaluate and persist only the D-005 Baseline x3 gate.

    This intentionally does not require the final evidence-safety file,
    Grafana export, cleanup result, or Spike output. D-005 must be decided
    immediately after Baseline x3 and before d005-record or Spike can run.
    """
    metadata = read_json(evidence_root / "metadata.json")
    k6_root = evidence_root / "k6"
    baseline_reps = []
    if k6_root.is_dir():
        for entry in sorted(k6_root.iterdir()):
            if entry.is_dir() and entry.name.startswith("baseline-"):
                baseline_reps.append(evaluate_phase(entry))
    source_commit_sha = metadata.get("commitSha")
    marker_profile_shas: list[str] = []
    marker_input_digests: list[str] = []
    marker_contract_passed = True
    stages_root = evidence_root / "stages"
    for index in (1, 2, 3):
        marker_path = stages_root / f"baseline-{index}.json"
        try:
            marker = read_json(marker_path)
        except ValidationError:
            marker_contract_passed = False
            continue
        if marker.get("runId") != metadata.get("runId") or marker.get("stage") != f"baseline-{index}":
            marker_contract_passed = False
        if marker.get("sourceCommitSha") != source_commit_sha:
            marker_contract_passed = False
        profile_sha = marker.get("profileSha256")
        if not isinstance(profile_sha, str) or not SHA256_PATTERN.fullmatch(profile_sha):
            marker_contract_passed = False
        else:
            marker_profile_shas.append(profile_sha)
        input_digest = marker.get("inputDigest")
        if not isinstance(input_digest, str) or not SHA256_PATTERN.fullmatch(input_digest):
            marker_contract_passed = False
        else:
            marker_input_digests.append(input_digest)
    profile_sha_values = set(marker_profile_shas)
    profile_sha_consistent = len(marker_profile_shas) == 3 and len(profile_sha_values) == 1
    # stage_input_digest intentionally includes baseline-1/2/3 as the stage
    # discriminator, so the three values must be present, valid, and distinct;
    # run/profile/source consistency above binds their shared inputs.
    input_digest_contract_passed = len(marker_input_digests) == 3 and len(set(marker_input_digests)) == 3
    source_sha_valid = isinstance(source_commit_sha, str) and COMMIT_SHA_PATTERN.fullmatch(source_commit_sha) is not None
    digest_gate_passed = (
        marker_contract_passed
        and profile_sha_consistent
        and input_digest_contract_passed
        and source_sha_valid
    )
    candidate = evaluate_baseline_candidate(
        baseline_reps,
        confirmed_rate,
        digest_gate_passed=digest_gate_passed,
    )
    report = {
        "evidenceRoot": str(evidence_root),
        "runId": metadata.get("runId"),
        "confirmedRate": confirmed_rate,
        "sourceCommitSha": source_commit_sha,
        "profileSha256": next(iter(profile_sha_values), None) if profile_sha_consistent else None,
        "profileShaConsistent": profile_sha_consistent,
        "baselineInputDigests": marker_input_digests,
        "inputDigestContractPassed": input_digest_contract_passed,
        "digestGatePassed": digest_gate_passed,
        "baselineReps": baseline_reps,
        "baselineCandidate": candidate,
        "passed": candidate["frozen"],
        "sloVersion": "v0.2-candidate (D-005 baseline gate)",
    }
    (evidence_root / "baseline-candidate.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def fixture_failure(phase: str, reason: str) -> dict:
    """Return a sanitized, machine-readable fixture rejection."""
    return {"phase": phase, "passed": False, "reason": reason}


def evaluate_fixture_phase(evidence_root: Path, run_id: str, phase: str) -> dict:
    """Validate the fixture artifact that belongs to one assessed phase."""
    marker_path = evidence_root / "stages" / f"{phase}.json"
    if not marker_path.exists():
        return fixture_failure(phase, "missing_stage_marker")
    try:
        marker = read_json(marker_path)
    except (ValidationError, OSError, json.JSONDecodeError):
        return fixture_failure(phase, "invalid_stage_marker")
    if marker.get("runId") != run_id:
        return fixture_failure(phase, "stage_run_id_mismatch")
    if marker.get("fixtureId") != phase:
        return fixture_failure(phase, "stage_fixture_id_mismatch")
    expected_path = f"fixtures/{phase}.json"
    if marker.get("fixtureResultPath") != expected_path:
        return fixture_failure(phase, "stage_fixture_path_mismatch")
    expected_users = marker.get("fixtureExpectedUsers")
    if not isinstance(expected_users, int) or isinstance(expected_users, bool) or expected_users < 1:
        return fixture_failure(phase, "invalid_expected_user_count")

    artifact_path = evidence_root / expected_path
    if not artifact_path.exists():
        return fixture_failure(phase, "missing_fixture_artifact")
    try:
        artifact = read_json(artifact_path)
    except (ValidationError, OSError, json.JSONDecodeError):
        return fixture_failure(phase, "invalid_fixture_artifact")
    if artifact.get("runId") != run_id:
        return fixture_failure(phase, "fixture_run_id_mismatch")
    if artifact.get("fixtureId") != phase:
        return fixture_failure(phase, "fixture_id_mismatch")

    expected = artifact.get("expected")
    expected_contract = {
        "users": expected_users,
        "planners": expected_users,
        "timelineItems": expected_users * TIMELINE_ITEMS_PER_PLANNER,
        "timelineItemsPerPlanner": TIMELINE_ITEMS_PER_PLANNER,
    }
    if expected != expected_contract:
        return fixture_failure(phase, "fixture_expected_count_mismatch")

    actual = artifact.get("actual")
    actual_contract = {
        "users": expected_users,
        "planners": expected_users,
        "timelineItems": expected_users * TIMELINE_ITEMS_PER_PLANNER,
        "minimumTimelineItemsPerPlanner": TIMELINE_ITEMS_PER_PLANNER,
        "maximumTimelineItemsPerPlanner": TIMELINE_ITEMS_PER_PLANNER,
    }
    if actual != actual_contract:
        return fixture_failure(phase, "fixture_actual_count_mismatch")
    return {
        "phase": phase,
        "passed": True,
        "fixtureId": phase,
        "fixtureResultPath": expected_path,
        "expectedUsers": expected_users,
        "actual": actual,
    }


def evaluate_fixture_evidence(evidence_root: Path, run_id: str) -> dict:
    phases = [evaluate_fixture_phase(evidence_root, run_id, phase) for phase in ASSESSED_PHASES]
    return {
        "passed": all(phase["passed"] for phase in phases),
        "phases": phases,
    }


def evaluate_bundle_structure(evidence_root: Path, data_file: Path | None) -> dict:
    metadata = read_json(evidence_root / "metadata.json")
    operations_path = evidence_root / "operations.jsonl"
    if not operations_path.exists():
        raise ValidationError("missing operations.jsonl at evidence root")
    events = {json.loads(line)["event"] for line in operations_path.read_text(encoding="utf-8").splitlines()}
    has_run_boundaries = "RUN_START" in events and "RUN_END" in events

    safety_path = evidence_root / "evidence-safety.json"
    if safety_path.exists():
        safety = json.loads(safety_path.read_text(encoding="utf-8"))
    elif data_file is not None:
        safety = load_safety_module().scan(evidence_root, data_file)
        safety_path.write_text(json.dumps(safety, indent=2) + "\n", encoding="utf-8")
    else:
        raise ValidationError("evidence-safety.json is missing and --data-file was not given to build it")

    return {
        "runId": metadata.get("runId"),
        "hasRunBoundaries": has_run_boundaries,
        "safetyFindingCount": safety.get("findingCount"),
        "safe": bool(safety.get("safe")),
    }


def evaluate(evidence_root: Path, data_file: Path | None, confirmed_rate: float | None) -> dict:
    structure = evaluate_bundle_structure(evidence_root, data_file)
    phases = discover_phases(evidence_root)
    baseline_candidate = evaluate_baseline_candidate(phases["baseline"], confirmed_rate)
    fixtures = evaluate_fixture_evidence(evidence_root, structure["runId"])

    smoke_pass = phases["smoke"] is not None and phases["smoke"]["k6ExitCode"] == 0 and phases["smoke"]["droppedIterations"] == 0
    ramp_pass = phases["ramp"] is not None and phases["ramp"]["k6ExitCode"] == 0 and phases["ramp"]["droppedIterations"] == 0
    spike_recorded = phases["spike"] is not None and phases["spike"]["k6ExitCode"] is not None

    report = {
        "evidenceRoot": str(evidence_root),
        "structure": structure,
        "smoke": phases["smoke"],
        "smokePass": smoke_pass,
        "ramp": phases["ramp"],
        "rampPass": ramp_pass,
        "baselineReps": phases["baseline"],
        "baselineCandidate": baseline_candidate,
        "spike": phases["spike"],
        "spikeRecorded": spike_recorded,
        "fixtures": fixtures,
        "sloVersion": "v0.2-candidate (not v1.0-frozen; see D-006 in decisions/OPEN_DECISIONS.md)",
    }
    report["passed"] = (
        structure["hasRunBoundaries"]
        and structure["safe"]
        and smoke_pass
        and ramp_pass
        and baseline_candidate["frozen"]
        and spike_recorded
        and fixtures["passed"]
    )
    (evidence_root / "gate-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--data-file", type=Path, default=None, help="Fallback to build evidence-safety.json if upload-aws-evidence.py has not already written one")
    parser.add_argument("--confirmed-rate", type=float, default=None, help="D-005 rate the operator confirmed for this run; cross-checked against each baseline rep's recorded rate")
    parser.add_argument(
        "--baseline-candidate-only",
        action="store_true",
        help="Evaluate and write baseline-candidate.json without requiring final evidence files",
    )
    args = parser.parse_args()
    if args.baseline_candidate_only:
        report = evaluate_baseline_candidate_only(
            args.evidence_root.resolve(),
            args.confirmed_rate,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["passed"] else 1
    report = evaluate(
        args.evidence_root.resolve(),
        args.data_file.resolve() if args.data_file else None,
        args.confirmed_rate,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"[validate] ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
