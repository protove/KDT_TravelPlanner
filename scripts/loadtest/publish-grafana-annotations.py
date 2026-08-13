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
}


def epoch_millis(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def payloads(run_dir: Path, context_tag: str) -> list[dict]:
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    payload = []
    for line in (run_dir / "operations.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        name = event["event"]
        if name not in EVENT_TAGS:
            continue
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
