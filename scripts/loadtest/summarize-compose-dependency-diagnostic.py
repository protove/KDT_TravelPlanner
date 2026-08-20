#!/usr/bin/env python3
"""Summarize controlled Compose diagnostic runs without changing thresholds."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


VARIANTS = {"refresh-only", "read-only", "fixed-cardinality-mixed", "growing-cardinality-mixed"}


class SummaryError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    return parser.parse_args()


def timestamp(value: str) -> float:
    value = value.replace("Z", "+00:00")
    match = re.fullmatch(r"(.+\.)(\d+)([+-]\d{2}:\d{2})", value)
    if match:
        value = f"{match.group(1)}{match.group(2)[:6].ljust(6, '0')}{match.group(3)}"
    return datetime.fromisoformat(value).timestamp()


def percentile(values: list[float], fraction: float = 0.95) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    result = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[index][1]:
            end += 1
        average = (index + end) / 2 + 1
        for position in range(index, end + 1):
            result[indexed[position][0]] = average
        index = end + 1
    return result


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    numerator = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in rx) * sum((y - my) ** 2 for y in ry))
    return numerator / denominator if denominator else 0.0


def read_points(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SummaryError(f"missing raw evidence: {path}")
    points: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            point = json.loads(line)
        except json.JSONDecodeError:
            continue
        if point.get("type") != "Point":
            continue
        data = point.get("data") or {}
        if not isinstance(data.get("time"), str) or not isinstance(data.get("value"), (int, float)):
            continue
        tags = data.get("tags") or {}
        points.append({
            "metric": point.get("metric"),
            "time": timestamp(data["time"]),
            "value": float(data["value"]),
            "tags": tags if isinstance(tags, dict) else {},
        })
    return points


def run_operation_summary(points: list[dict[str, Any]], variant: str, operation: str) -> dict[str, Any]:
    selected = [p for p in points if p["metric"] == "http_req_duration" and p["tags"].get("diagnostic_operation") == operation]
    selected = [p for p in selected if p["tags"].get("diagnostic_phase", "measured") == "measured"] or selected
    selected.sort(key=lambda item: item["time"])
    if not selected:
        return {"variant": variant, "operation": operation, "samples": 0, "firstQuartileP95Ms": None, "lastQuartileP95Ms": None, "degradationRatio": None}
    split = max(1, len(selected) // 4)
    first = [p["value"] for p in selected[:split]]
    last = [p["value"] for p in selected[-split:]]
    first_p95, last_p95 = percentile(first), percentile(last)
    return {
        "variant": variant,
        "operation": operation,
        "samples": len(selected),
        "firstQuartileP95Ms": first_p95,
        "lastQuartileP95Ms": last_p95,
        "degradationRatio": (last_p95 / first_p95) if first_p95 and last_p95 is not None else None,
    }


def item_duration_correlation(points: list[dict[str, Any]], variant: str, operation: str) -> float | None:
    counts: dict[int, list[float]] = defaultdict(list)
    durations: dict[int, list[float]] = defaultdict(list)
    for point in points:
        if point["tags"].get("diagnostic_phase", "measured") != "measured":
            continue
        bucket = int(point["time"] // 60)
        if point["metric"] == "diagnostic_reorder_item_count" and point["tags"].get("diagnostic_operation") == operation:
            counts[bucket].append(point["value"])
        if point["metric"] == "http_req_duration" and point["tags"].get("diagnostic_operation") == operation:
            durations[bucket].append(point["value"])
    keys = sorted(set(counts) & set(durations))
    return spearman([statistics.mean(counts[key]) for key in keys], [statistics.mean(durations[key]) for key in keys])


def load_run(run_dir: Path) -> dict[str, Any]:
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "run-status.json").read_text(encoding="utf-8"))
    if status.get("k6ExitCode") != 0:
        raise SummaryError(f"invalid k6 run status: {run_dir}")
    points = read_points(run_dir / "raw.json")
    operations = sorted({p["tags"].get("diagnostic_operation") for p in points if p["metric"] == "http_req_duration" and p["tags"].get("diagnostic_operation")})
    summaries = [run_operation_summary(points, metadata["variant"], operation) for operation in operations]
    correlations = {}
    for operation in ("alternatingThreeItemReorder", "reverseAllItemsReorder"):
        correlation = item_duration_correlation(points, metadata["variant"], operation)
        if correlation is not None:
            correlations[operation] = correlation
    return {"replicate": metadata["replicate"], "variant": metadata["variant"], "operations": summaries, "itemDurationSpearman": correlations, "pointCount": len(points), "runDir": str(run_dir)}


def classify(runs: list[dict[str, Any]], smoke: bool) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_variant[run["variant"]].append(run)

    def ratios(variant: str, operation_names: set[str]) -> list[float]:
        output = []
        for run in by_variant.get(variant, []):
            for operation in run["operations"]:
                if operation["operation"] in operation_names and operation["degradationRatio"] is not None:
                    output.append(operation["degradationRatio"])
        return output

    growing = ratios("growing-cardinality-mixed", {"reverseAllItemsReorder"})
    fixed = ratios("fixed-cardinality-mixed", {"alternatingThreeItemReorder"})
    refresh = ratios("refresh-only", {"refresh"})
    read = ratios("read-only", {"travelList", "travelDetail", "mapPoints"})
    growing_rho = [rho for run in by_variant.get("growing-cardinality-mixed", []) for rho in run["itemDurationSpearman"].values()]
    enough = all(len(by_variant.get(variant, [])) >= 2 for variant in VARIANTS)
    rules = {
        "growingWorkloadSupported": enough and sum(value >= 2.0 for value in growing) >= 2 and (not fixed or all(value < 1.25 for value in fixed)) and (not refresh or all(value < 1.25 for value in refresh)) and (not read or all(value < 1.25 for value in read)) and sum(value >= 0.70 for value in growing_rho) >= 2,
        "postgresSupported": enough and sum(value >= 1.50 for value in read + fixed + growing) >= 2 and (not refresh or all(value < 1.25 for value in refresh)),
        "redisSupported": enough and sum(value >= 1.50 for value in refresh) >= 2 and (not read or all(value < 1.25 for value in read)),
        "backendOrRuntimeSupported": enough and all(ratios(variant, {"refresh", "travelList", "travelDetail", "mapPoints", "alternatingThreeItemReorder", "reverseAllItemsReorder"}) for variant in VARIANTS),
    }
    if smoke:
        verdict = "inconclusive"
        reason = "smoke run is a contract check and does not satisfy the 2/3 replicate rule"
    elif rules["growingWorkloadSupported"]:
        verdict = "probable-growing-cardinality-db-round-trip"
        reason = "growing reorder degraded while fixed/read/refresh controls did not and item-count correlation met the pre-fixed threshold"
    elif rules["redisSupported"]:
        verdict = "probable-redis"
        reason = "refresh-only degraded with Redis control metrics to be checked in the same UTC windows"
    elif rules["postgresSupported"]:
        verdict = "probable-postgresql"
        reason = "read/write database paths degraded across controls while refresh-only remained stable"
    elif rules["backendOrRuntimeSupported"]:
        verdict = "probable-backend-or-runtime"
        reason = "all controlled variants degraded together"
    else:
        verdict = "inconclusive"
        reason = "pre-fixed classification rules were not met consistently across the required replicates"
    return {"verdict": verdict, "reason": reason, "rules": rules, "sampleCounts": {"growing": len(growing), "fixed": len(fixed), "refresh": len(refresh), "read": len(read)}}


def summarize(evidence_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in sorted(evidence_root.glob("replicate-*/*/metadata.json")):
        runs.append(load_run(path.parent))
    if not runs:
        raise SummaryError("no completed diagnostic variant runs found")
    smoke = json.loads((evidence_root / "campaign-metadata.json").read_text(encoding="utf-8")).get("smoke", False)
    verdict = classify(runs, bool(smoke))
    summary = {"schemaVersion": "compose-diagnostic-summary/v1", "campaignId": evidence_root.name.removesuffix("-dependency-diagnostic"), "generatedAtUtc": datetime.utcnow().isoformat() + "Z", "runs": runs, "verdict": verdict}
    (evidence_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (evidence_root / "verdict.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(evidence_root, summary, verdict)
    return summary, verdict


def write_report(evidence_root: Path, summary: dict[str, Any], verdict: dict[str, Any]) -> None:
    lines = [
        "# SCRUM-41 Compose DB/Redis 지연 진단 보고서",
        "",
        f"- Campaign: `{summary['campaignId']}`",
        f"- 판정: **{verdict['verdict']}**",
        f"- 근거 요약: {verdict['reason']}",
        "",
        "## 통제 설계",
        "",
        "20 RPS, 3분 warmup + 10분 measured, 20 preallocated VU/40 max VU로 refresh-only, read-only, fixed-cardinality-mixed, growing-cardinality-mixed를 replicate 순서를 교차해 실행했다.",
        "",
        "## 관측 사실",
        "",
        "| replicate | variant | operation | samples | first p95 (ms) | last p95 (ms) | degradation | Spearman |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for run in summary["runs"]:
        correlations = run.get("itemDurationSpearman", {})
        for operation in run["operations"]:
            rho = correlations.get(operation["operation"])
            lines.append(
                f"| {run['replicate']} | {run['variant']} | {operation['operation']} | {operation['samples']} | "
                f"{operation['firstQuartileP95Ms'] if operation['firstQuartileP95Ms'] is not None else '-'} | "
                f"{operation['lastQuartileP95Ms'] if operation['lastQuartileP95Ms'] is not None else '-'} | "
                f"{operation['degradationRatio'] if operation['degradationRatio'] is not None else '-'} | "
                f"{rho if rho is not None else '-'} |"
            )
    lines.extend([
        "",
        "## Grafana 증거",
        "",
        "각 replicate의 고정 UTC window에 대해 dashboard 전체 PNG, 핵심 panel PNG, Prometheus query JSON과 capture-status를 함께 보존했다.",
    ])
    for run_dir in sorted(evidence_root.glob("replicate-*")):
        if not run_dir.is_dir():
            continue
        lines.append(
            f"- `{run_dir.name}`: `{run_dir.name}/grafana/dashboard-full.png`, "
            f"`{run_dir.name}/grafana/panels/`, `{run_dir.name}/grafana/queries/`, "
            f"`{run_dir.name}/grafana/capture-status.json`"
        )
    lines.extend([
        "",
        "## 추론과 한계",
        "",
        "위 표는 k6 raw point에서 계산한 진단 통계다. probable 판정은 plan에 고정한 2/3 replicate·ratio·Spearman 규칙만 적용하며, 불리한 결과를 이유로 재실행하지 않는다.",
        "",
        "이 실험은 로컬 Compose의 synthetic data와 exporter metric을 사용하므로 AWS EC2/ASG/RDS/ElastiCache 성능이나 운영 SLO로 일반화할 수 없다. PostgreSQL/Redis exporter가 제공하지 않는 query-level latency는 추정하지 않는다.",
        "",
        "## 후속 권고",
        "",
        "판정이 growing-cardinality 계열이면 timeline reorder의 item count, DB round-trip, Hikari pending을 우선 확인하고, Redis 계열이면 refresh-only와 Redis command/client/memory 지표의 같은 UTC window를 대조한다. inconclusive이면 추가 실험 설계가 필요하며 사후 threshold 변경은 금지한다.",
        "",
    ])
    (evidence_root / "DIAGNOSTIC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    try:
        summary, verdict = summarize(Path(parse_args().evidence_root).resolve())
    except (SummaryError, OSError, json.JSONDecodeError) as error:
        print(f"[diagnostic-summary] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"runCount": len(summary["runs"]), "verdict": verdict["verdict"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
