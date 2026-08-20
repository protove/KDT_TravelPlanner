#!/usr/bin/env python3
"""Aggregate sealed SCRUM-41 SQL round-trip evidence using fixed rules."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COUNTS = (3, 10, 25, 50, 100, 200)
MODES = ("noop", "reverse")
REVERSE_TOLERANCE = 0.05


class SummaryError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def percentile(values: list[float], fraction: float = 0.95) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    output = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[index][1]:
            end += 1
        average = (index + end) / 2 + 1
        for position in range(index, end + 1):
            output[indexed[position][0]] = average
        index = end + 1
    return output


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    numerator = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in rx) * sum((y - my) ** 2 for y in ry))
    return numerator / denominator if denominator else 0.0


def number(value: object, default: float | None = None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SummaryError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise SummaryError(f"JSON object required: {path}")
    return value


def k6_metrics(stage_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    native = load_json(stage_dir / "k6-native-summary.json")
    compact_path = stage_dir / "summary.json"
    compact = load_json(compact_path) if compact_path.is_file() else native
    metrics = native.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise SummaryError(f"k6 metrics missing: {stage_dir}")
    return metrics, compact


def metric_values(metrics: dict[str, Any], name: str) -> dict[str, Any]:
    """Read both k6's native flat metric shape and fixture value wrappers."""
    metric = metrics.get(name) or {}
    if not isinstance(metric, dict):
        return {}
    values = metric.get("values")
    return values if isinstance(values, dict) else metric


def metric_rate(metrics: dict[str, Any], name: str) -> float:
    values = metric_values(metrics, name)
    for key in ("rate", "value"):
        value = number(values.get(key), None)
        if value is not None:
            return value
    fails = number(values.get("fails"), None)
    passes = number(values.get("passes"), None)
    if fails is not None and passes is not None and fails + passes > 0:
        return fails / (fails + passes)
    return 0.0


def read_stats(stage_dir: Path) -> dict[str, Any]:
    stats = load_json(stage_dir / "pg-stat-statements.json")
    statements = stats.get("statements")
    if not isinstance(statements, list):
        raise SummaryError(f"pg_stat_statements statements missing: {stage_dir}")
    return stats


def stage_summary(stage_dir: Path) -> dict[str, Any]:
    metadata = load_json(stage_dir / "metadata.json")
    status = load_json(stage_dir / "run-status.json")
    if status.get("k6ExitCode") != 0:
        raise SummaryError(f"k6 exit code is non-zero: {stage_dir}")
    mode = str(metadata.get("mode"))
    item_count = int(metadata.get("itemCount"))
    if mode not in MODES or item_count not in COUNTS:
        raise SummaryError(f"invalid stage dimensions: {stage_dir}")
    metrics, compact = k6_metrics(stage_dir)
    duration = metric_values(metrics, "http_req_duration")
    p95 = number(duration.get("p(95)"))
    if p95 is None:
        raise SummaryError(f"http_req_duration p95 missing: {stage_dir}")
    requests = number(metric_values(metrics, "http_reqs").get("count"), 0.0) or 0.0
    successful = number(metric_values(metrics, "sql_diagnostic_successful_requests").get("count"), requests) or 0.0
    contract_metric = metric_values(metrics, "sql_diagnostic_contract_failures")
    contract_rate_value = number(contract_metric.get("rate"), None)
    if contract_rate_value is None:
        # k6's native JSON summary names a Rate metric's aggregate `value`;
        # retain support for the explicit `rate` shape used by fixtures.
        contract_rate_value = number(contract_metric.get("value"), None)
    if contract_rate_value is None:
        fails = number(contract_metric.get("fails"), None)
        passes = number(contract_metric.get("passes"), None)
        if fails is not None and passes is not None and fails + passes > 0:
            contract_rate_value = fails / (fails + passes)
    contract_rate = 1.0 if contract_rate_value is None else contract_rate_value
    http_failed_rate = metric_rate(metrics, "http_req_failed")
    unexpected_error_rate = metric_rate(metrics, "unexpected_errors")
    generic_contract_failure_rate = metric_rate(metrics, "contract_fail")
    dropped = number(metric_values(metrics, "dropped_iterations").get("count"), 0.0) or 0.0
    stats = read_stats(stage_dir)
    if int(stats.get("unknownCount", 0)) != 0:
        raise SummaryError(f"unknown SQL family present: {stage_dir}")
    family_values: dict[str, dict[str, float]] = {}
    for statement in stats["statements"]:
        family = str(statement.get("queryFamily"))
        if family not in family_values:
            family_values[family] = {"calls": 0.0, "rows": 0.0, "totalExecMs": 0.0, "meanExecMs": 0.0, "sharedBlksRead": 0.0, "tempBlksWritten": 0.0, "walBytes": 0.0, "blkReadMs": 0.0, "blkWriteMs": 0.0}
        target = family_values[family]
        for key in ("calls", "rows", "totalExecMs", "sharedBlksRead", "tempBlksWritten", "walBytes", "blkReadMs", "blkWriteMs"):
            target[key] += number(statement.get(key), 0.0) or 0.0
        target["meanExecMs"] = target["totalExecMs"] / target["calls"] if target["calls"] else 0.0
    total_calls = sum(value["calls"] for value in family_values.values())
    total_db_ms = sum(value["totalExecMs"] for value in family_values.values())
    update_calls = family_values.get("timeline_update", {}).get("calls", 0.0)
    update_rows = family_values.get("timeline_update", {}).get("rows", 0.0)
    calls_per_request = total_calls / successful if successful else None
    update_calls_per_request = update_calls / successful if successful else None
    update_rows_per_request = update_rows / successful if successful else None
    db_ms_per_request = total_db_ms / successful if successful else None
    mean_update_ms = family_values.get("timeline_update", {}).get("meanExecMs", 0.0)
    metric_delta = load_json(stage_dir / "backend-metric-delta.json")
    return {
        "replicate": int(metadata["replicate"]),
        "mode": mode,
        "itemCount": item_count,
        "stage": stage_dir.name,
        "path": str(stage_dir),
        "valid": bool(metadata.get("canonicalAfterMeasured", False)) and requests == successful and successful == float(metadata.get("measuredIterations", 30)) and contract_rate == 0 and generic_contract_failure_rate == 0 and http_failed_rate == 0 and unexpected_error_rate == 0 and dropped == 0,
        "validity": {
            "successfulRequests": successful,
            "measuredIterations": int(metadata.get("measuredIterations", 30)),
            "contractFailureRate": contract_rate,
            "genericContractFailureRate": generic_contract_failure_rate,
            "httpFailedRate": http_failed_rate,
            "unexpectedErrorRate": unexpected_error_rate,
            "droppedIterations": dropped,
            "canonicalAfterMeasured": bool(metadata.get("canonicalAfterMeasured", False)),
            "unknownSqlFamilies": int(stats.get("unknownCount", 0)),
        },
        "apiP95Ms": p95,
        "apiMeanMs": number(duration.get("avg"), None),
        "requestBodyBytesP95": number(metric_values(metrics, "sql_diagnostic_request_body_bytes").get("p(95)"), None),
        "totalSqlCallsPerRequest": calls_per_request,
        "timelineUpdateCallsPerRequest": update_calls_per_request,
        "timelineUpdateRowsPerRequest": update_rows_per_request,
        "totalDbExecMsPerRequest": db_ms_per_request,
        "timelineUpdateMeanExecMsPerCall": mean_update_ms,
        "residualMsPerRequest": max(0.0, (number(duration.get("avg"), 0.0) or 0.0) - (db_ms_per_request or 0.0)),
        "family": family_values,
        "stats": {
            "resetAtUtc": stats.get("resetAtUtc"),
            "snapshotAtUtc": stats.get("snapshotAtUtc"),
            "deadlocks": number(metric_delta.get("after", {}).get("pg_stat_database_deadlocks", 0), 0.0) or 0.0,
            "tempFiles": sum(value.get("tempBlksWritten", 0.0) for value in family_values.values()),
        },
        "compactSummary": compact.get("scenario"),
    }


def ratio(last: float | None, first: float | None) -> float | None:
    return last / first if last is not None and first not in (None, 0) else None


def by_dimensions(stages: list[dict[str, Any]], mode: str, replicate: int) -> dict[int, dict[str, Any]]:
    return {int(stage["itemCount"]): stage for stage in stages if stage["mode"] == mode and stage["replicate"] == replicate}


def replicate_features(stages: list[dict[str, Any]], replicate: int) -> dict[str, Any]:
    reverse = by_dimensions(stages, "reverse", replicate)
    noop = by_dimensions(stages, "noop", replicate)
    counts = sorted(set(reverse) & set(noop))
    reverse_calls = [reverse[count]["timelineUpdateCallsPerRequest"] or 0.0 for count in counts]
    reverse_p95 = [reverse[count]["apiP95Ms"] for count in counts]
    count_values = [float(count) for count in counts]
    expected = [3 * (count // 2) for count in counts]
    call_shape = all(abs(actual - wanted) <= max(1.0, wanted * REVERSE_TOLERANCE) for actual, wanted in zip(reverse_calls, expected))
    noop_zero = all(abs(noop[count]["timelineUpdateCallsPerRequest"] or 0.0) <= 1e-9 for count in counts)
    update_rho = spearman(count_values, reverse_calls)
    api_rho = spearman(count_values, reverse_p95)
    reverse_p95_ratio = ratio(reverse.get(200, {}).get("apiP95Ms"), reverse.get(3, {}).get("apiP95Ms")) if 200 in reverse and 3 in reverse else None
    reverse_calls_ratio = ratio(reverse.get(200, {}).get("totalSqlCallsPerRequest"), reverse.get(3, {}).get("totalSqlCallsPerRequest")) if 200 in reverse and 3 in reverse else None
    reverse_db_ratio = ratio(reverse.get(200, {}).get("totalDbExecMsPerRequest"), reverse.get(3, {}).get("totalDbExecMsPerRequest")) if 200 in reverse and 3 in reverse else None
    reverse_mean_call_ratio = ratio(reverse.get(200, {}).get("timelineUpdateMeanExecMsPerCall"), reverse.get(3, {}).get("timelineUpdateMeanExecMsPerCall")) if 200 in reverse and 3 in reverse else None
    reverse_noop_200_ratio = ratio(reverse.get(200, {}).get("apiP95Ms"), noop.get(200, {}).get("apiP95Ms")) if 200 in reverse and 200 in noop else None
    noop_api_ratio = ratio(noop.get(200, {}).get("apiP95Ms"), noop.get(3, {}).get("apiP95Ms")) if 200 in noop and 3 in noop else None
    no_lock_signal = all((stage["stats"]["deadlocks"] or 0) == 0 and (stage["stats"]["tempFiles"] or 0) == 0 for stage in reverse.values())
    return {
        "replicate": replicate,
        "counts": counts,
        "noopUpdateCallsZero": noop_zero,
        "reverseExpectedUpdateCalls": expected,
        "reverseObservedUpdateCalls": reverse_calls,
        "reverseUpdateShape": call_shape,
        "reverseUpdateCallsSpearman": update_rho,
        "reverseApiP95Spearman": api_rho,
        "reverseApiP95Ratio200To3": reverse_p95_ratio,
        "reverseSqlCallsRatio200To3": reverse_calls_ratio,
        "reverseDbExecRatio200To3": reverse_db_ratio,
        "reverseMeanCallRatio200To3": reverse_mean_call_ratio,
        "reverseToNoopApiP95RatioAt200": reverse_noop_200_ratio,
        "noopApiP95Ratio200To3": noop_api_ratio,
        "timelineUpdateMeanExecMsMax": max((stage["timelineUpdateMeanExecMsPerCall"] for stage in reverse.values()), default=None),
        "noLockOrTempSpillSignal": no_lock_signal,
        "confirmedRepeatedSqlRoundTrips": bool(
            noop_zero and call_shape and (update_rho or -1) >= 0.95 and (reverse_calls_ratio or 0) >= 20
            and (api_rho or -1) >= 0.80 and (reverse_p95_ratio or 0) >= 2.0
            and (replicate and max((stage["timelineUpdateMeanExecMsPerCall"] for stage in reverse.values()), default=999) <= 5.0)
            and no_lock_signal and (reverse_noop_200_ratio or 0) >= 2.0
        ),
    }


def classify(stages: list[dict[str, Any]], replicate_features_list: list[dict[str, Any]], required_replicates: int) -> dict[str, Any]:
    valid_replicates = {int(stage["replicate"]) for stage in stages if stage["valid"]}
    enough = len(valid_replicates) >= required_replicates
    confirmed_count = sum(1 for feature in replicate_features_list if feature["confirmedRepeatedSqlRoundTrips"])
    slow_count = 0
    payload_count = 0
    mixed_count = 0
    for feature in replicate_features_list:
        if feature["reverseSqlCallsRatio200To3"] is not None and feature["reverseSqlCallsRatio200To3"] < 2.0 and (feature["reverseApiP95Ratio200To3"] or 0) >= 2.0 and max(feature["reverseDbExecRatio200To3"] or 0, feature["reverseMeanCallRatio200To3"] or 0) >= 2.0:
            slow_count += 1
        if (feature["noopApiP95Ratio200To3"] or 0) >= 2.0 and (feature["reverseToNoopApiP95RatioAt200"] or 0) < 1.25:
            payload_count += 1
        if (feature["reverseSqlCallsRatio200To3"] or 0) >= 2.0 and ((feature["timelineUpdateMeanExecMsMax"] or 0) > 5.0 or (feature["reverseMeanCallRatio200To3"] or 0) >= 2.0):
            mixed_count += 1
    if not enough:
        verdict, reason = "inconclusive", "필수 replicate가 유효하지 않아 2/3 일치 규칙을 적용할 수 없다."
    elif confirmed_count >= 2:
        verdict, reason = "confirmed-repeated-sql-round-trips", "reverse에서 itemCount와 UPDATE 호출 수가 함께 증가하고 개별 UPDATE 실행시간은 사전 임계값 아래였다."
    elif slow_count >= 2:
        verdict, reason = "probable-slow-individual-sql", "SQL 호출 수 증가는 제한적인데 API와 DB 실행시간이 함께 악화됐다."
    elif payload_count >= 2:
        verdict, reason = "probable-application-or-payload", "noop payload도 악화됐지만 DB 호출/실행시간 증가가 원인을 지지하지 않았다."
    elif mixed_count >= 2:
        verdict, reason = "mixed-db-amplification", "SQL 호출 증폭과 개별 SQL 실행시간 악화가 동시에 관찰됐다."
    else:
        verdict, reason = "inconclusive", "사전 고정 분류 규칙 중 어느 branch도 2/3 replicate 일치를 얻지 못했다."
    return {
        "schemaVersion": "scrum41-sql-round-trip-verdict/v1",
        "jiraKey": "SCRUM-41",
        "verdict": verdict,
        "reason": reason,
        "requiredReplicateAgreement": 2,
        "validReplicates": sorted(valid_replicates),
        "agreement": {"confirmedRepeatedSqlRoundTrips": confirmed_count, "probableSlowIndividualSql": slow_count, "probableApplicationOrPayload": payload_count, "mixedDbAmplification": mixed_count},
        "rules": {
            "thresholdSource": "plan-v1.yaml classification_rules",
            "reverseUpdateTolerance": REVERSE_TOLERANCE,
            "timelineUpdateMeanExecMsMax": 5.0,
            "apiP95SpearmanMin": 0.80,
            "reverseUpdateCallsSpearmanMin": 0.95,
            "apiP95RatioMin": 2.0,
        },
    }


def write_report(root: Path, summary: dict[str, Any], verdict: dict[str, Any]) -> None:
    lines = [
        "# SCRUM-41 Compose SQL round-trip 진단 보고서",
        "",
        f"- Campaign: `{summary['campaignId']}`",
        f"- 판정: **{verdict['verdict']}**",
        f"- 근거: {verdict['reason']}",
        "",
        "## 확인한 질문",
        "",
        "동일 payload cardinality의 noop과 실제 순서 변경 reverse를 비교해, 단일 SQL 자체의 실행시간 악화인지 반복 UPDATE/flush 왕복 증폭인지 분리했다.",
        "",
        "## 관측 사실",
        "",
        "| replicate | mode | itemCount | API p95 ms | SQL calls/request | UPDATE calls/request | DB ms/request | mean UPDATE ms/call | valid |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for stage in sorted(summary["stages"], key=lambda value: (value["replicate"], value["itemCount"], value["mode"])):
        lines.append(f"| {stage['replicate']} | {stage['mode']} | {stage['itemCount']} | {stage['apiP95Ms']:.3f} | {stage['totalSqlCallsPerRequest'] if stage['totalSqlCallsPerRequest'] is not None else '-'} | {stage['timelineUpdateCallsPerRequest'] if stage['timelineUpdateCallsPerRequest'] is not None else '-'} | {stage['totalDbExecMsPerRequest'] if stage['totalDbExecMsPerRequest'] is not None else '-'} | {stage['timelineUpdateMeanExecMsPerCall']:.3f} | {'PASS' if stage['valid'] else 'FAIL'} |")
    lines.extend(["", "## replicate별 상관/비율", "", "| replicate | UPDATE Spearman | API p95 Spearman | API p95 200→3 | SQL calls 200→3 | reverse/noop p95 @200 |", "|---:|---:|---:|---:|---:|---:|"])
    for feature in summary["replicateFeatures"]:
        lines.append(f"| {feature['replicate']} | {feature['reverseUpdateCallsSpearman']} | {feature['reverseApiP95Spearman']} | {feature['reverseApiP95Ratio200To3']} | {feature['reverseSqlCallsRatio200To3']} | {feature['reverseToNoopApiP95RatioAt200']} |")
    lines.extend([
        "",
        "## 해석",
        "",
        "### 사실과 추론",
        "",
        "`calls/request`는 pg_stat_statements의 호출 횟수를 성공 요청 수로 나눈 값이고, `mean UPDATE ms/call`은 개별 UPDATE의 PostgreSQL 평균 실행시간이다. API residual은 API 평균에서 관측 DB 실행시간을 뺀 값일 뿐 네트워크, JDBC, JPA flush, 애플리케이션 처리를 단일 원인으로 단정하지 않는다.",
        "",
        f"사전 고정 규칙으로 계산한 최종 판정은 **{verdict['verdict']}**이며, 사후 threshold 조정이나 성능 결과를 이유로 한 재실행은 하지 않았다.",
        "",
        "### 한계",
        "",
        "이 결과는 합성 fixture와 local Compose의 PostgreSQL/Redis를 이용한 원인 분리 실험이다. EC2 ASG, RDS, ElastiCache의 운영 SLO나 실제 production workload로 일반화하지 않는다. SQL query text는 literal을 제거해 family로 분류했으며 unknown family가 있으면 해당 stage를 invalid로 취급한다.",
        "",
        "### Grafana 증거",
        "",
        "각 replicate의 고정 UTC window와 dashboard/panel PNG, Prometheus query JSON은 다음 경로에 보존했다.",
    ])
    for replicate in sorted({stage["replicate"] for stage in summary["stages"]}):
        lines.append(f"- `replicate-{replicate}/grafana/dashboard-full.png` 및 `replicate-{replicate}/grafana/panels/`, `queries/`, `capture-status.json`")
    lines.extend(["", "## 다음 조치", "", "confirmed branch라면 production 최적화 이슈를 별도로 설계하되, 본 진단 commit에서는 service/repository SQL을 변경하지 않는다.", ""])
    (root / "SQL_DIAGNOSTIC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def summarize(root: Path, *, required_replicates: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = load_json(root / "campaign-metadata.json")
    replicate_dirs = sorted(path for path in root.glob("replicate-*") if path.is_dir())
    stages: list[dict[str, Any]] = []
    for replicate_dir in replicate_dirs:
        for stage_dir in sorted((replicate_dir / "stages").glob("*-*")):
            if stage_dir.is_dir():
                stages.append(stage_summary(stage_dir))
    if not stages:
        raise SummaryError("no stage evidence found")
    required = required_replicates if required_replicates is not None else int(metadata.get("replicates", len(replicate_dirs)))
    features = [replicate_features(stages, replicate) for replicate in sorted({int(stage["replicate"]) for stage in stages})]
    verdict = classify(stages, features, required)
    summary = {
        "schemaVersion": "scrum41-sql-round-trip-summary/v1",
        "jiraKey": "SCRUM-41",
        "campaignId": metadata.get("campaignId", root.name),
        "generatedAtUtc": utc_now(),
        "profile": metadata.get("profile"),
        "stages": stages,
        "replicateFeatures": features,
        "validity": {"stageCount": len(stages), "validStageCount": sum(1 for stage in stages if stage["valid"]), "requiredReplicates": required},
        "verdict": verdict,
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "verdict.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(root, summary, verdict)
    return summary, verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--required-replicates", type=int, default=None)
    args = parser.parse_args()
    try:
        summary, verdict = summarize(args.evidence_root.resolve(), required_replicates=args.required_replicates)
    except (SummaryError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[sql-summary] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"campaignId": summary["campaignId"], "stageCount": len(summary["stages"]), "verdict": verdict["verdict"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
