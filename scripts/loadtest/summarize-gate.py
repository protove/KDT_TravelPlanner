#!/usr/bin/env python3
"""Validate a completed Compose Gate manifest and emit a sanitized report."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[2]
SAFETY_SCRIPT = REPOSITORY_ROOT / "scripts/loadtest/verify-evidence-safety.py"
MAX_TAG_NAMES = 20


def load_safety_module():
    spec = importlib.util.spec_from_file_location("verify_evidence_safety", SAFETY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def percent(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)%\s*", value)
    return float(match.group(1)) if match else None


def runner_stats(path: Path) -> dict:
    stats_path = path / "runner-stats.jsonl"
    if not stats_path.exists():
        return {
            "samples": 0,
            "maxCpuPercent": None,
            "maxMemoryPercent": None,
            "networkSamples": 0,
        }
    samples = 0
    network_samples = 0
    cpu_values: list[float] = []
    memory_values: list[float] = []
    for line in stats_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            docker = record.get("docker", {})
        except json.JSONDecodeError:
            continue
        if not isinstance(docker, dict):
            continue
        samples += 1
        cpu = percent(docker.get("CPUPerc"))
        memory = percent(docker.get("MemPerc"))
        if cpu is not None:
            cpu_values.append(cpu)
        if memory is not None:
            memory_values.append(memory)
        if docker.get("NetIO"):
            network_samples += 1
    return {
        "samples": samples,
        "maxCpuPercent": max(cpu_values) if cpu_values else None,
        "maxMemoryPercent": max(memory_values) if memory_values else None,
        "networkSamples": network_samples,
    }


def tag_cardinality(path: Path) -> dict:
    names: set[str] = set()
    raw_path = path / "raw.json"
    if raw_path.exists():
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            try:
                point = json.loads(line)
            except json.JSONDecodeError:
                continue
            tags = point.get("data", {}).get("tags", {})
            if isinstance(tags, dict) and isinstance(tags.get("name"), str):
                names.add(tags["name"])
    dynamic_name = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
    return {
        "uniqueNames": len(names),
        "names": sorted(names),
        "controlled": len(names) <= MAX_TAG_NAMES and not any(dynamic_name.search(name) for name in names),
    }


def scenario_result(path: Path, scenario: str, expected: dict) -> dict:
    status = read_json(path / "run-status.json")
    metadata = read_json(path / "metadata.json")
    summary = read_json(path / "summary.json")
    result = {
        "scenario": scenario,
        "directory": str(path),
        "k6ExitCode": status.get("k6ExitCode"),
        "metadata": {
            key: metadata.get(key)
            for key in ("runId", "scenario", "commitSha", "k6Image", "rate", "seedVersion", "composeProject")
        },
        "requests": summary.get("metrics", {}).get("http_reqs", {}).get("count"),
        "p95Ms": summary.get("metrics", {}).get("http_req_duration", {}).get("p(95)"),
        "unexpectedErrorRate": summary.get("metrics", {}).get("unexpected_errors", {}).get("rate"),
        "contractFailureRate": summary.get("metrics", {}).get("contract_fail", {}).get("rate"),
        "droppedIterations": summary.get("metrics", {}).get("dropped_iterations"),
        "thresholds": summary.get("thresholds", {}),
        "checks": summary.get("metrics", {}).get("checks", {}),
        "tagCardinality": tag_cardinality(path),
    }
    result["metadataMatchesProfile"] = all(metadata.get(key) == value for key, value in expected.items())
    result["droppedIterationsPresent"] = "dropped_iterations" in summary.get("metrics", {})
    result["runnerStats"] = runner_stats(path)
    result["runnerStatsSamples"] = result["runnerStats"]["samples"]
    result["passed"] = (
        status.get("k6ExitCode") == 0
        and result["metadataMatchesProfile"]
        and result["tagCardinality"]["controlled"]
    )
    if scenario == "baseline":
        threshold_values = [
            value is True
            for metric_thresholds in result["thresholds"].values()
            for value in metric_thresholds.values()
        ]
        result["thresholdsPresent"] = bool(threshold_values)
        result["thresholdsPassed"] = result["thresholdsPresent"] and all(threshold_values)
        result["passed"] = result["passed"] and result["thresholdsPassed"]
    if scenario == "recovery":
        verdict = read_json(path / "verdict.json")
        events = [json.loads(line)["event"] for line in (path / "operations.jsonl").read_text(encoding="utf-8").splitlines()]
        result["verdict"] = {
            key: verdict.get(key)
            for key in ("T1", "T4", "T5", "T6", "recoverySeconds", "budgetSeconds", "withinBudget")
        }
        result["events"] = events
        result["passed"] = result["passed"] and verdict.get("withinBudget") is True and verdict.get("T4") is not None and verdict.get("T6") is not None and "T4" in events and "T6" in events
    if scenario == "spike":
        result["passed"] = result["passed"] and result["droppedIterationsPresent"] and result["runnerStatsSamples"] > 0
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-file", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = read_json(manifest_path)
    profile = manifest["profile"]
    expected = {
        "commitSha": None,
        "k6Image": profile["k6Image"],
        "rate": profile["rate"],
        "seedVersion": profile["seedVersion"],
    }
    results = []
    for run in manifest.get("runs", []):
        for directory in run["scenarios"]:
            path = Path(directory)
            if path.name.endswith("-recovery-recovery-steady"):
                scenario = "recovery"
            else:
                scenario = path.name.rsplit("-", 1)[-1]
            if scenario not in {"smoke", "baseline", "recovery", "spike"}:
                raise ValueError(f"unsupported scenario directory: {path}")
            if expected["commitSha"] is None:
                expected["commitSha"] = read_json(path / "metadata.json").get("commitSha")
            result = scenario_result(path, scenario, expected)
            results.append(result)

    safety_module = load_safety_module()
    safety_results = []
    for result in results:
        safety_results.append(safety_module.scan(Path(result["directory"]), args.data_file.resolve()))
    report = {
        "gateId": manifest.get("gateId"),
        "profileVersion": profile.get("profileVersion"),
        "commitSha": expected["commitSha"],
        "runs": results,
        "safety": safety_results,
        "passed": manifest.get("status") == "completed" and all(item["passed"] for item in results) and all(item["safe"] for item in safety_results),
    }
    output = manifest_path.with_name("gate-report.json")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if report["passed"]:
        print(f"[gate] passed: {output}")
        return 0
    print(f"[gate] FAILED: {output}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"[gate] ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
