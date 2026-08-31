#!/usr/bin/env python3
"""Publish sanitized rehearsal events as Grafana annotations."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


EVENT_TAGS = {
    "RUN_START": "test-start",
    "RUN_END": "test-end",
    "T0": "baseline-stable",
    "T1": "failure-injected",
    "T2": "target-excluded",
    "T3": "failure-detected",
    "T4": "recovery-start",
    "T5": "target-healthy",
    "T5_FAIL": "target-health-failed",
    "T6": "slo-recovered",
    "STAGE_START": "adaptive-stage-start",
    "STAGE_END": "adaptive-stage-end",
    "STAGE_EXTENSION": "adaptive-stage-extension",
    "TERMINAL": "breakpoint-terminal",
    "INCOMPLETE": "incomplete-stop",
}


def epoch_millis(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def payloads(run_dir: Path, context_tag: str) -> list[dict]:
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    payload = []
    event_times: list[int] = []
    for line in (run_dir / "operations.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        name = event["event"]
        if name not in EVENT_TAGS:
            continue
        event_times.append(epoch_millis(event["ts"]))
        payload.append({
            "time": epoch_millis(event["ts"]),
            "tags": [
                context_tag,
                EVENT_TAGS[name],
                f"scenario:{metadata.get('scenario', 'unknown')}",
                f"run:{metadata.get('runId', run_dir.name)}",
            ],
            "text": f"{name}: {str(event.get('detail', ''))[:200]}",
        })
    mock_path = run_dir / "mock" / "evidence.json"
    if mock_path.is_file():
        mock = json.loads(mock_path.read_text(encoding="utf-8"))
        health = mock.get("health") if isinstance(mock.get("health"), dict) else {}
        requests = mock.get("requests") if isinstance(mock.get("requests"), dict) else {}
        headroom = mock.get("headroom") if isinstance(mock.get("headroom"), dict) else {}
        validity = str(mock.get("validity", "unknown"))[:32]
        health_state = "ok" if health.get("ok") is True else "failed"
        five_xx = int(requests.get("http5xxLines", 0) or 0)
        cpu = headroom.get("maxCpuPercent")
        memory = headroom.get("maxMemoryPercent")
        headroom_state = "limited" if any(
            isinstance(value, (int, float)) and value >= 90 for value in (cpu, memory)
        ) else "ok"
        started_at = metadata.get("startedAtUtc")
        fallback_time = epoch_millis(started_at) if isinstance(started_at, str) else 0
        annotation_time = max(event_times or [fallback_time])
        payload.append({
            "time": annotation_time,
            "tags": [
                context_tag,
                "mock-validity",
                f"mock-validity:{validity}",
                f"mock-health:{health_state}",
                f"mock-5xx:{min(max(five_xx, 0), 999999)}",
                f"mock-headroom:{headroom_state}",
                f"scenario:{metadata.get('scenario', 'unknown')}",
                f"run:{metadata.get('runId', run_dir.name)}",
                "provenance:runner-mock-evidence",
            ],
            "text": (
                "MOCK_VALIDITY: "
                f"validity={validity} health={health_state} "
                f"requests={min(max(int(requests.get('accessLogLines', 0) or 0), 0), 999999)} "
                f"http5xx={min(max(five_xx, 0), 999999)} "
                f"maxCpuPercent={cpu} maxMemoryPercent={memory}; "
                "source=mock/evidence.json (Runner-local sealed evidence)"
            )[:500],
        })
    return payload


def fetch_existing(url: str, auth: str, run_tag: str, times: list[int]) -> list[dict]:
    if not times:
        return []
    window_from = min(times) - 60_000
    window_to = max(times) + 60_000
    request = Request(
        f"{url.rstrip('/')}/api/annotations?type=annotation&limit=500"
        f"&from={window_from}&to={window_to}&tags={quote(run_tag)}",
        headers={"Authorization": f"Basic {auth}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            existing = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Grafana annotation lookup failed: {error}") from error
    return existing if isinstance(existing, list) else []


def publish(run_dir: Path, url: str, user: str, password: str, dry_run: bool, context_tag: str) -> dict:
    annotations = payloads(run_dir, context_tag)
    results = []
    auth = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    existing_keys: set[tuple[int, str, tuple[str, ...]]] = set()
    if annotations and not dry_run:
        run_tag = next(tag for tag in annotations[0]["tags"] if tag.startswith("run:"))
        for item in fetch_existing(url, auth, run_tag, [entry["time"] for entry in annotations]):
            existing_keys.add(
                (
                    int(item.get("time", 0)),
                    str(item.get("text", "")),
                    tuple(sorted(item.get("tags", []))),
                )
            )
    for annotation in annotations:
        key = (annotation["time"], annotation["text"], tuple(sorted(annotation["tags"])))
        if key in existing_keys:
            results.append({"status": "duplicate-skipped", "time": annotation["time"], "tags": annotation["tags"]})
            continue
        if dry_run:
            results.append({"status": "dry-run", "time": annotation["time"], "tags": annotation["tags"]})
            continue
        request = Request(
            f"{url.rstrip('/')}/api/annotations",
            data=json.dumps(annotation).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                results.append({"status": response.status, "time": annotation["time"], "tags": annotation["tags"]})
        except (HTTPError, URLError) as error:
            raise RuntimeError(f"Grafana annotation request failed: {error}") from error
    return {
        "runDirectory": str(run_dir),
        "grafanaUrl": url,
        "dryRun": dry_run,
        "contextTag": context_tag,
        "annotationCount": len(results),
        "skippedDuplicates": sum(1 for item in results if item["status"] == "duplicate-skipped"),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--grafana-url", default=os.environ.get("GRAFANA_URL", "http://127.0.0.1:3001"))
    parser.add_argument("--user", default=os.environ.get("GRAFANA_ADMIN_USER", ""))
    parser.add_argument("--password", default=os.environ.get("GRAFANA_ADMIN_PASSWORD", ""))
    parser.add_argument(
        "--context-tag",
        default="compose-rehearsal",
        help="First annotation tag; use aws-recovery for AWS Recovery runs",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and (not args.user or not args.password):
        print("[grafana] --user/--password or GRAFANA_ADMIN_* are required", file=sys.stderr)
        return 2
    try:
        result = publish(args.run_dir.resolve(), args.grafana_url, args.user, args.password, args.dry_run, args.context_tag)
    except (OSError, KeyError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        print(f"[grafana] ERROR: {error}", file=sys.stderr)
        return 1
    output = args.run_dir / "grafana-annotations.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[grafana] annotations={result['annotationCount']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
