#!/usr/bin/env python3
"""Compare the SCRUM-41 bulk timeline-order campaign with the frozen baseline."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = ROOT / "scripts/loadtest/summarize-compose-sql-round-trip-diagnostic.py"
COUNTS = [3, 10, 25, 50, 100, 200]
MODES = ["noop", "reverse"]
BASELINE_REQUIRED_FILES = {
    "summary": "summary.json",
    "verdict": "verdict.json",
    "report": "SQL_DIAGNOSTIC_REPORT.md",
    "profile": "effective-profile.json",
    "manifest": "campaign-manifest.json",
}
BASELINE_METRICS = {
    "n200ReverseApiP95MedianMs": 83.106,
    "n200ReverseDbExecMedianMs": 13.3254025,
    "n200ReverseUpdateCallsPerRequest": 300.0,
}
THRESHOLDS = {
    "reverseUpdateCallsTolerance": 0.05,
    "reverseUpdateRowsTolerance": 0.05,
    "totalSqlCallsRatioMax": 1.25,
    "updateReductionMin": 0.99,
    "apiP95MedianFactorMax": 0.70,
    "dbExecMedianFactorMax": 0.50,
    "p95RatioMax": 2.0,
    "agreementMin": 2,
}
EXPECTED_BASELINE_HASHES = {
    "summary": "8e85179d702746841753eed52c9d1bff0ae304a6b59b9f496e1a1887ceaa34cb",
    "verdict": "602a04464fa69023a9f3ecf053f2f8dd22c72bc125ebc4a9d7f02d28d5754b33",
    "report": "7f21da5cc6fa4129bc526560692018021e12a7adb40b858bf9379d38e944ff84",
    "profile": "6e33f856fbc380c578b576634370814e76f419b381b0f344a9b93324b7ec2172",
    "overlay": "0e0ae0569367b9970890034e1719e90db2496493fb160c0515d3120c48d22fd1",
    "dashboard": "e13bf2f778506c762312d47e87e616759e9e6e8073302c637016d3c5ac3eea8e",
}


class OptimizationError(RuntimeError):
    pass


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise OptimizationError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUMMARY = load_module("scrum41_optimization_sql_summary", SUMMARY_PATH)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OptimizationError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise OptimizationError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_signature(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "itemCounts": profile.get("itemCounts"),
        "modes": profile.get("modes"),
        "warmupIterations": profile.get("warmupIterations"),
        "measuredIterations": profile.get("measuredIterations"),
        "virtualUsers": profile.get("virtualUsers"),
        "pacingSeconds": profile.get("pacingSeconds"),
        "replicates": profile.get("replicates"),
        "orderByReplicate": profile.get("orderByReplicate"),
    }


def stage_dirs(root: Path) -> list[Path]:
    return sorted(
        stage
        for replicate in root.glob("replicate-*")
        if replicate.is_dir()
        for stage in (replicate / "stages").glob("*-*")
        if stage.is_dir()
    )


def normalize_stage(stage: dict[str, Any]) -> dict[str, Any]:
    if "timelineUpdateRowsPerRequest" not in stage:
        family = stage.get("family") or {}
        update = family.get("timeline_update") or {}
        successful = float((stage.get("validity") or {}).get("successfulRequests") or 0)
        stage["timelineUpdateRowsPerRequest"] = (float(update.get("rows") or 0) / successful) if successful else None
    return stage


def read_summary_stages(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    stages: list[dict[str, Any]] = []
    errors: list[str] = []
    for stage_dir in stage_dirs(root):
        try:
            stages.append(normalize_stage(SUMMARY.stage_summary(stage_dir)))
        except Exception as error:  # fail closed but preserve the reason in comparison.json
            errors.append(f"{stage_dir.relative_to(root)}: {error}")
    return stages, errors


def dimensions(stages: list[dict[str, Any]]) -> set[tuple[int, str]]:
    return {(int(stage["itemCount"]), str(stage["mode"])) for stage in stages}


def by_rep_mode_count(stages: list[dict[str, Any]], replicate: int, mode: str, count: int) -> dict[str, Any] | None:
    return next((stage for stage in stages if int(stage["replicate"]) == replicate and stage["mode"] == mode and int(stage["itemCount"]) == count), None)


def close_to(value: float | None, expected: float, tolerance: float) -> bool:
    return value is not None and abs(value - expected) <= max(0.05, abs(expected) * tolerance)


def median_or_none(values: list[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return statistics.median(numbers) if numbers else None


def validate_baseline(root: Path, provenance_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    provenance = load_json(provenance_path)
    for key, filename in BASELINE_REQUIRED_FILES.items():
        if not (root / filename).is_file():
            raise OptimizationError(f"baseline artifact missing: {filename}")
        expected = EXPECTED_BASELINE_HASHES.get(key)
        hash_target = ROOT / "load-tests/sql-diagnostic-profile.json" if key == "profile" else root / filename
        if expected and sha256(hash_target) != expected:
            raise OptimizationError(f"baseline artifact hash mismatch: {filename}")
        provenance_hash = provenance.get(key)
        if provenance_hash and provenance_hash != sha256(hash_target):
            raise OptimizationError(f"baseline provenance mismatch: {key}")
    for key in ("profile", "overlay", "dashboard"):
        if provenance.get(key) and EXPECTED_BASELINE_HASHES[key] != provenance[key]:
            raise OptimizationError(f"baseline provenance fixed hash mismatch: {key}")
    manifest = load_json(root / "campaign-manifest.json")
    manifest_digests = manifest.get("sourceDigests") or {}
    for key in ("profile", "overlay", "dashboard"):
        if manifest_digests.get(key) != EXPECTED_BASELINE_HASHES[key]:
            raise OptimizationError(f"baseline manifest digest mismatch: {key}")
    return load_json(root / "summary.json"), manifest, provenance


def validate_optimized_provenance(root: Path, baseline_manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = load_json(root / "campaign-manifest.json")
    validate_optimized_provenance_from_manifests(manifest, baseline_manifest)
    return manifest


def validate_optimized_provenance_from_manifests(manifest: dict[str, Any], baseline_manifest: dict[str, Any]) -> None:
    optimized_digests = manifest.get("sourceDigests") or {}
    baseline_digests = baseline_manifest.get("sourceDigests") or {}
    compared_keys = ["profile", "overlay", "prometheus", "dashboard", "k6Image", "pushgatewayImage"]
    mismatches = {
        key: {"baseline": baseline_digests.get(key), "optimized": optimized_digests.get(key)}
        for key in compared_keys
        if baseline_digests.get(key) != optimized_digests.get(key)
    }
    if mismatches:
        raise OptimizationError(f"profile/overlay/image digest mismatch: {sorted(mismatches)}")


def stage_valid(stage: dict[str, Any]) -> bool:
    validity = stage.get("validity") or {}
    return bool(stage.get("valid")) and float(validity.get("contractFailureRate") or 0) == 0 and float(validity.get("genericContractFailureRate") or 0) == 0 and float(validity.get("httpFailedRate") or 0) == 0 and float(validity.get("unexpectedErrorRate") or 0) == 0 and float(validity.get("droppedIterations") or 0) == 0


def evaluate(stages: list[dict[str, Any]], baseline_stages: list[dict[str, Any]], *, smoke: bool, errors: list[str], baseline_errors: list[str], optimized_manifest: dict[str, Any], baseline_manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_dimensions = {(count, mode) for count in COUNTS for mode in MODES}
    actual_dimensions = dimensions(stages)
    complete = not errors and actual_dimensions == expected_dimensions and len(stages) == 36
    all_valid = complete and all(stage_valid(stage) for stage in stages)
    replicates = sorted({int(stage["replicate"]) for stage in stages})
    hard_checks: dict[str, Any] = {
        "stageCount": {"actual": len(stages), "expected": 36, "pass": len(stages) == 36},
        "validEvidence": {"actual": all_valid, "pass": all_valid},
        "noopUpdateCallsZero": {"pass": all((stage.get("mode") != "noop" or abs(float(stage.get("timelineUpdateCallsPerRequest") or 0)) <= 1e-9) for stage in stages)},
        "reverseUpdateCallsOne": {"pass": all(stage.get("mode") != "reverse" or close_to(stage.get("timelineUpdateCallsPerRequest"), 1.0, THRESHOLDS["reverseUpdateCallsTolerance"]) for stage in stages)},
        "reverseUpdatedRowsPerRequestItemCount": {"pass": all(stage.get("mode") != "reverse" or close_to(stage.get("timelineUpdateRowsPerRequest"), float(stage.get("itemCount")), THRESHOLDS["reverseUpdateRowsTolerance"]) for stage in stages)},
        "deadlocksAndErrorsZero": {"pass": all(float((stage.get("stats") or {}).get("deadlocks") or 0) == 0 and stage_valid(stage) for stage in stages)},
    }
    per_replicate: list[dict[str, Any]] = []
    for replicate in replicates:
        reverse3 = by_rep_mode_count(stages, replicate, "reverse", 3)
        reverse200 = by_rep_mode_count(stages, replicate, "reverse", 200)
        noop200 = by_rep_mode_count(stages, replicate, "noop", 200)
        total_sql_ratio = (float(reverse200["totalSqlCallsPerRequest"]) / float(reverse3["totalSqlCallsPerRequest"])) if reverse3 and reverse200 and reverse3.get("totalSqlCallsPerRequest") else None
        p95_ratio = (float(reverse200["apiP95Ms"]) / float(reverse3["apiP95Ms"])) if reverse3 and reverse200 and reverse3.get("apiP95Ms") is not None and reverse200.get("apiP95Ms") is not None else None
        noop_ratio = (float(reverse200["apiP95Ms"]) / float(noop200["apiP95Ms"])) if reverse200 and noop200 and reverse200.get("apiP95Ms") is not None and noop200.get("apiP95Ms") is not None else None
        baseline200 = by_rep_mode_count(baseline_stages, replicate, "reverse", 200)
        update_reduction = None
        if baseline200 and baseline200.get("timelineUpdateCallsPerRequest") not in (None, 0):
            update_reduction = 1 - float(reverse200.get("timelineUpdateCallsPerRequest") or 0) / float(baseline200["timelineUpdateCallsPerRequest"]) if reverse200 else None
        per_replicate.append({
            "replicate": replicate,
            "totalSqlCallsRatio200To3": total_sql_ratio,
            "reverseApiP95Ratio200To3": p95_ratio,
            "reverseNoopApiP95RatioAt200": noop_ratio,
            "n200ReverseUpdateReduction": update_reduction,
            "sqlRatioPass": total_sql_ratio is not None and total_sql_ratio <= THRESHOLDS["totalSqlCallsRatioMax"],
            "p95RatioPass": p95_ratio is not None and p95_ratio <= THRESHOLDS["p95RatioMax"] and noop_ratio is not None and noop_ratio <= THRESHOLDS["p95RatioMax"],
            "updateReductionPass": update_reduction is not None and update_reduction >= THRESHOLDS["updateReductionMin"],
        })
    n200_reverse = [stage for stage in stages if stage.get("mode") == "reverse" and int(stage.get("itemCount")) == 200]
    api_median = median_or_none([stage.get("apiP95Ms") for stage in n200_reverse])
    db_median = median_or_none([stage.get("totalDbExecMsPerRequest") for stage in n200_reverse])
    sql_ratio_pass = sum(1 for entry in per_replicate if entry["sqlRatioPass"]) >= THRESHOLDS["agreementMin"]
    p95_ratio_pass = sum(1 for entry in per_replicate if entry["p95RatioPass"]) >= THRESHOLDS["agreementMin"]
    update_reduction_pass = all(entry["updateReductionPass"] for entry in per_replicate) and len(per_replicate) == 3
    baseline_api_median = median_or_none([stage.get("apiP95Ms") for stage in baseline_stages if stage.get("mode") == "reverse" and int(stage.get("itemCount")) == 200])
    baseline_db_median = median_or_none([stage.get("totalDbExecMsPerRequest") for stage in baseline_stages if stage.get("mode") == "reverse" and int(stage.get("itemCount")) == 200])
    baseline_metrics_pass = baseline_api_median is not None and baseline_db_median is not None and abs(baseline_api_median - BASELINE_METRICS["n200ReverseApiP95MedianMs"]) < 1e-3 and abs(baseline_db_median - BASELINE_METRICS["n200ReverseDbExecMedianMs"]) < 1e-3
    api_pass = api_median is not None and api_median <= BASELINE_METRICS["n200ReverseApiP95MedianMs"] * THRESHOLDS["apiP95MedianFactorMax"]
    db_pass = db_median is not None and db_median <= BASELINE_METRICS["n200ReverseDbExecMedianMs"] * THRESHOLDS["dbExecMedianFactorMax"]
    sql_pass = all(hard_checks[name]["pass"] for name in ("stageCount", "validEvidence", "noopUpdateCallsZero", "reverseUpdateCallsOne", "reverseUpdatedRowsPerRequestItemCount", "deadlocksAndErrorsZero")) and sql_ratio_pass and update_reduction_pass
    latency_available = api_median is not None and db_median is not None and bool(per_replicate)
    latency_pass = baseline_metrics_pass and api_pass and db_pass and p95_ratio_pass
    if smoke:
        verdict = "optimization-smoke-functional-check"
        reason = "smoke profile is intentionally smaller than the fixed 36-stage campaign; full thresholds are deferred to N90."
    elif not all_valid or baseline_errors or len(baseline_stages) < 36:
        verdict = "inconclusive-invalid-evidence"
        reason = "evidence validity, stage completeness, or baseline provenance was not sufficient for a fixed comparison."
    elif sql_pass and latency_pass:
        verdict = "confirmed-round-trip-reduction"
        reason = "bulk update shape and all precommitted latency/ratio comparison rules passed."
    elif sql_pass and not latency_available:
        verdict = "confirmed-sql-reduction-latency-inconclusive"
        reason = "functional SQL reduction passed but required latency measurements were unavailable."
    else:
        verdict = "optimization-insufficient"
        reason = "the valid run did not satisfy every precommitted optimization or latency threshold; thresholds were not changed."
    comparison = {
        "schemaVersion": "scrum41-timeline-order-optimization-comparison/v1",
        "jiraKey": "SCRUM-41",
        "generatedAtUtc": utc_now(),
        "baselineCampaignId": baseline_manifest.get("campaignId"),
        "optimizedCampaignId": optimized_manifest.get("campaignId"),
        "smoke": smoke,
        "thresholds": THRESHOLDS,
        "baselineMetrics": {**BASELINE_METRICS, "observedApiP95MedianMs": baseline_api_median, "observedDbExecMedianMs": baseline_db_median, "fixedMetricsMatch": baseline_metrics_pass},
        "optimizedMetrics": {"n200ReverseApiP95MedianMs": api_median, "n200ReverseDbExecMedianMs": db_median},
        "hardChecks": hard_checks,
        "replicates": per_replicate,
        "aggregateChecks": {"sqlCallsRatioAgreementPass": sql_ratio_pass, "updateReductionAllReplicatesPass": update_reduction_pass, "apiP95MedianPass": api_pass, "dbExecMedianPass": db_pass, "p95RatioAgreementPass": p95_ratio_pass, "latencyAvailable": latency_available, "sqlPass": sql_pass, "latencyPass": latency_pass},
        "sourceDigests": {"baseline": baseline_manifest.get("sourceDigests"), "optimized": optimized_manifest.get("sourceDigests")},
        "errors": errors,
    }
    verdict_payload = {"schemaVersion": "scrum41-timeline-order-optimization-verdict/v1", "jiraKey": "SCRUM-41", "verdict": verdict, "reason": reason, "thresholdSource": "immutable plan-v1.yaml", "comparison": "comparison.json"}
    return comparison, verdict_payload


def write_report(root: Path, comparison: dict[str, Any], verdict: dict[str, Any]) -> None:
    aggregate = comparison["aggregateChecks"]
    lines = [
        "# SCRUM-41 Timeline order bulk update 최적화 보고서",
        "",
        f"- Campaign: `{comparison['optimizedCampaignId']}`",
        f"- 최종 고정 규칙 판정: **{verdict['verdict']}**",
        f"- 근거: {verdict['reason']}",
        "",
        "## 관측 사실",
        "",
        f"- reverse 요청의 `timeline_update` 호출/request와 rows/request는 각 stage에서 hard check로 계산했다.",
        f"- N=200 reverse API p95 replicate median: `{comparison['optimizedMetrics']['n200ReverseApiP95MedianMs']}` ms (baseline 고정 median `{comparison['baselineMetrics']['n200ReverseApiP95MedianMs']}` ms).",
        f"- N=200 reverse DB execution/request replicate median: `{comparison['optimizedMetrics']['n200ReverseDbExecMedianMs']}` ms (baseline 고정 median `{comparison['baselineMetrics']['n200ReverseDbExecMedianMs']}` ms).",
        f"- SQL shape pass: `{aggregate['sqlPass']}`; latency comparison pass: `{aggregate['latencyPass']}`.",
        "",
        "## 추론",
        "",
        "single parameterized bulk UPDATE와 row-lock snapshot이 반복 saveAndFlush 왕복을 제거했는지는 위 SQL family 호출/rows 지표로 지지한다. API p95 변화는 DB 실행시간만으로 단일 원인을 단정하지 않고, JDBC·transaction·application residual을 포함한 Compose 관측 결과로 해석한다.",
        "",
        "## Compose 한계",
        "",
        "이 결과는 synthetic fixture와 local Compose PostgreSQL/Redis에서의 원인 분리다. EC2 ASG, RDS, ElastiCache 운영 SLO나 실제 workload로 일반화하지 않는다.",
        "",
        "## 운영 migration 주의",
        "",
        "V13은 기존 unique constraint를 drop/add해 DEFERRABLE INITIALLY IMMEDIATE로 재생성한다. 운영 적용 전 lock/배포 창, concurrent writer drain, rollback 절차를 별도로 검토해야 하며 이 실행은 production migration/deploy를 수행하지 않는다.",
        "",
        "## 고정 threshold",
        "",
        f"`comparison.json`의 threshold와 baseline digest가 immutable plan-v1.yaml 및 baseline-provenance.json과 일치해야 하며, 성능 미달을 이유로 사후 threshold 변경이나 선택적 재실행은 허용하지 않는다.",
        "",
    ]
    (root / "OPTIMIZATION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def summarize(root: Path, baseline_root: Path, baseline_provenance: Path, *, smoke: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_summary, baseline_manifest, _ = validate_baseline(baseline_root, baseline_provenance)
    optimized_manifest = validate_optimized_provenance(root, baseline_manifest)
    optimized_stages, errors = read_summary_stages(root)
    baseline_stages = [normalize_stage(dict(stage)) for stage in baseline_summary.get("stages", []) if isinstance(stage, dict)]
    comparison, verdict = evaluate(optimized_stages, baseline_stages, smoke=smoke, errors=errors, baseline_errors=[], optimized_manifest=optimized_manifest, baseline_manifest=baseline_manifest)
    summary = {"schemaVersion": "scrum41-timeline-order-optimization-summary/v1", "jiraKey": "SCRUM-41", "campaignId": optimized_manifest.get("campaignId", root.name), "generatedAtUtc": utc_now(), "stages": optimized_stages, "comparison": "comparison.json", "verdict": verdict}
    write_json(root / "summary.json", summary)
    write_json(root / "comparison.json", comparison)
    write_json(root / "verdict.json", verdict)
    write_report(root, comparison, verdict)
    return summary, verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--baseline-provenance", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    try:
        _, verdict = summarize(args.evidence_root.resolve(), args.baseline_root.resolve(), args.baseline_provenance.resolve(), smoke=args.smoke)
    except (OptimizationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[timeline-optimization] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"verdict": verdict["verdict"], "evidenceRoot": str(args.evidence_root.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
