#!/usr/bin/env python3
"""Rank reproducible MSA-boundary hotspot candidates from sealed metrics."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


class AnalysisError(ValueError):
    """A fail-closed analysis input error."""


def _number(value: object, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if value == value else default


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _read_points(path: Path, candidate: str) -> tuple[list[float], int, int]:
    """Read only bounded operation-tagged duration points from a k6 raw stream."""
    durations: list[float] = []
    errors = 0
    total = 0
    if not path.is_file():
        return durations, errors, total
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("metric") != "http_req_duration" or item.get("type") != "Point":
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            tags = data.get("tags") if isinstance(data.get("tags"), dict) else {}
            if candidate not in {
                tags.get("service"), tags.get("domain"), tags.get("subdomain"), tags.get("operationId"),
            }:
                continue
            value = _number(data.get("value"), default=-1.0)
            if value < 0:
                continue
            total += 1
            durations.append(value)
            try:
                status = int(str(tags.get("status", "0")))
            except ValueError:
                status = 0
            if status == 0 or status >= 500:
                errors += 1
    return durations, errors, total


def _stage_rate(stage: Path, prefix: str) -> int | None:
    match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", stage.name)
    return int(match.group(1)) if match else None


def _stage_is_usable(stage: Path) -> tuple[bool, bool, dict]:
    """Return (usable, stable, result) without treating a clean stage as a terminal."""
    controller = {}
    result = {}
    for name, target in (("controller-result.json", controller), ("capacity-stress-result.json", result)):
        path = stage / name
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                value = {}
            if isinstance(value, dict):
                target.update(value)
    if controller.get("terminalReason") not in {
        "STAGE_COMPLETE", "NODE_MAX_PENDING", "NODE_SCALE_NOT_TRIGGERED", "NODE_SCALE_FAILED",
        "NODE_COMPUTE_SATURATION", "SLO_COLLAPSE", "THROUGHPUT_PLATEAU", "HPA_CAPACITY_EXHAUSTED",
        "BACKEND_OOM", "BACKEND_UNHEALTHY", "ALB_SATURATION", "DATA_TIER_SATURATION",
    }:
        return False, False, result
    if not (stage / "raw.json").is_file():
        return False, False, result
    window = result.get("snapshotWindow") if isinstance(result.get("snapshotWindow"), dict) else {}
    complete_windows = _number(window.get("completeSloWindows"), default=0.0)
    if complete_windows < 2:
        return False, False, result
    runner = result.get("runner") if isinstance(result.get("runner"), dict) else {}
    mock = result.get("mock") if isinstance(result.get("mock"), dict) else {}
    if runner.get("invalid") is True or mock.get("validity") not in {None, "VALID"}:
        return False, False, result
    stable = (
        controller.get("terminalReason") == "STAGE_COMPLETE"
        and _number(window.get("sloBreachedWindows"), default=0.0) == 0
    )
    return True, stable, result


def _stage_dropped_rate(stage: Path) -> float:
    path = stage / "summary.json"
    if not path.is_file():
        return 0.0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0.0
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    dropped = metrics.get("dropped_iterations") if isinstance(metrics.get("dropped_iterations"), dict) else {}
    iterations = metrics.get("iterations") if isinstance(metrics.get("iterations"), dict) else {}
    dropped_count = _number(dropped.get("count"), default=0.0)
    completed = _number(iterations.get("count"), default=0.0)
    denominator = completed + dropped_count
    return dropped_count / denominator if denominator > 0 else 0.0


def build_candidate_metrics(evidence_root: Path, profile: dict, stage_prefix: str = "balanced") -> dict:
    """Build deterministic hotspot scores from sealed balanced-stage raw data."""
    stress = profile.get("capacityStress") if isinstance(profile.get("capacityStress"), dict) else {}
    candidate_order = [item for item in stress.get("hotspotCandidateOrder", []) if isinstance(item, str) and item]
    if len(candidate_order) < 2:
        raise AnalysisError("profile hotspot candidate order must contain at least two names")
    stages = []
    k6_root = evidence_root / "k6"
    for path in k6_root.iterdir() if k6_root.is_dir() else []:
        rate = _stage_rate(path, stage_prefix) if path.is_dir() else None
        if rate is not None:
            stages.append((rate, path))
    stages.sort(key=lambda item: item[0])
    if not stages:
        raise AnalysisError(f"no {stage_prefix}-<rate> evidence directories found")

    valid_stage_rates: list[int] = []
    stable_stage_rates: list[int] = []
    stage_sources: dict[str, list[str]] = {candidate: [] for candidate in candidate_order}
    rows: dict[str, list[dict]] = {candidate: [] for candidate in candidate_order}
    for rate, stage in stages:
        usable, stable, result = _stage_is_usable(stage)
        if not usable:
            continue
        valid_stage_rates.append(rate)
        if stable:
            stable_stage_rates.append(rate)
        dropped_rate = _stage_dropped_rate(stage)
        for candidate in candidate_order:
            durations, errors, total = _read_points(stage / "raw.json", candidate)
            if not durations:
                continue
            p95 = _percentile(durations, 0.95)
            error_rate = errors / total if total else 0.0
            breach = (p95 is not None and p95 > 500.0) or error_rate >= 0.01
            rows[candidate].append({
                "rate": rate,
                "samples": total,
                "p95Ms": round(p95, 6) if p95 is not None else None,
                "errorRate": round(error_rate, 8),
                "droppedRate": round(dropped_rate, 8),
                "sloBreach": bool(breach),
                "source": f"k6/{stage.name}/raw.json",
            })
            stage_sources[candidate].append(f"k6/{stage.name}/raw.json")

    metrics = []
    for candidate in candidate_order:
        candidate_rows = rows[candidate]
        if not candidate_rows:
            metrics.append({"candidate": candidate, "complete": False, "evidence": []})
            continue
        breaches = [row for row in candidate_rows if row["sloBreach"]]
        p95_ratios = [row["p95Ms"] / 500.0 for row in candidate_rows if row.get("p95Ms") is not None]
        errors = [row["errorRate"] for row in candidate_rows]
        first_breach = min((row["rate"] for row in breaches), default=None)
        metrics.append({
            "candidate": candidate,
            "complete": True,
            "sloBreachWindows": len(breaches),
            "firstSloBreachRate": first_breach,
            "p95SloRatio": round(max(p95_ratios, default=0.0), 8),
            "errorRate": round(max(errors, default=0.0), 8),
            "droppedRate": round(max((row["droppedRate"] for row in candidate_rows), default=0.0), 8),
            "driverScore": round(max(p95_ratios, default=0.0), 8),
            "evidence": sorted(set(stage_sources[candidate])),
            "stageMetrics": candidate_rows,
        })
    if not valid_stage_rates:
        raise AnalysisError("no complete balanced-stage metric windows are available")
    stable_rate = max(stable_stage_rates, default=16)
    return {
        "schemaVersion": "scrum80-hotspot-metrics/v1",
        "candidateOrder": candidate_order,
        "candidateMetrics": metrics,
        "source": {
            "evidenceRoot": str(evidence_root),
            "stagePrefix": stage_prefix,
            "completeStageRates": valid_stage_rates,
            "stableStageRates": stable_stage_rates,
            "highestStableRate": stable_rate,
            "rateSelection": "highest complete STAGE_COMPLETE window without an SLO breach; fallback 16",
        },
    }


def rank_candidates(records: list[dict], candidate_order: list[str]) -> list[dict]:
    if not isinstance(records, list):
        raise AnalysisError("candidate metrics must be an array")
    order = {name: index for index, name in enumerate(candidate_order)}
    usable = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("candidate"), str):
            continue
        if record.get("complete") is not True:
            continue
        candidate = record["candidate"]
        usable.append({
            "candidate": candidate,
            "complete": True,
            "sloBreachWindows": int(_number(record.get("sloBreachWindows"))),
            "firstSloBreachRate": (_number(record.get("firstSloBreachRate"), default=math.inf)
                                   if record.get("firstSloBreachRate") is not None else math.inf),
            "p95SloRatio": _number(record.get("p95SloRatio")),
            "errorRate": _number(record.get("errorRate")),
            "droppedRate": _number(record.get("droppedRate")),
            "driverScore": _number(record.get("driverScore")),
            "evidence": list(record.get("evidence") or []),
        })
    if len({item["candidate"] for item in usable}) < 2:
        raise AnalysisError("at least two complete candidate records are required")
    usable.sort(key=lambda item: (
        item["firstSloBreachRate"],
        -item["sloBreachWindows"],
        -item["p95SloRatio"],
        -item["errorRate"],
        -item["droppedRate"],
        -item["driverScore"],
        order.get(item["candidate"], len(order)),
    ))
    ranked = []
    for rank, item in enumerate(usable, start=1):
        ranked.append({**item, "rank": rank})
    return ranked


def select_top_two(records: list[dict], candidate_order: list[str]) -> dict:
    ranked = rank_candidates(records, candidate_order)
    return {
        "schemaVersion": "scrum80-hotspot-selection/v1",
        "selectionRule": [
            "complete-only",
            "earliest-slo-breach",
            "p95-slo-ratio",
            "error-and-dropped-rate",
            "driver-corroboration",
            "stable-candidate-order",
        ],
        "ranked": ranked,
        "selected": [item["candidate"] for item in ranked[:2]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="JSON with candidateMetrics and candidateOrder")
    parser.add_argument("--evidence-root", type=Path, help="Sealed run root containing k6/<stage>-<rate>/raw.json")
    parser.add_argument("--profile", type=Path, help="MSA-boundary profile used to resolve candidate order")
    parser.add_argument("--stage-prefix", default="balanced", help="Stage directory prefix (default: balanced)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if bool(args.input) == bool(args.evidence_root):
            raise AnalysisError("provide exactly one of --input or --evidence-root")
        if args.evidence_root:
            if not args.profile:
                raise AnalysisError("--profile is required with --evidence-root")
            profile = json.loads(args.profile.read_text(encoding="utf-8"))
            payload = build_candidate_metrics(args.evidence_root, profile, args.stage_prefix)
        else:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = select_top_two(payload.get("candidateMetrics", []), payload.get("candidateOrder", []))
        if "source" in payload:
            result["source"] = payload["source"]
        if "candidateMetrics" in payload:
            result["candidateMetrics"] = payload["candidateMetrics"]
    except (OSError, json.JSONDecodeError, AnalysisError) as error:
        print(f"ERROR: {error}")
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
