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


def payloads(run_dir: Path) -> list[dict]:
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
                "compose-rehearsal",
                EVENT_TAGS[name],
                f"scenario:{metadata.get('scenario', 'unknown')}",
                f"run:{metadata.get('runId', run_dir.name)}",
            ],
            "text": f"{name}: {str(event.get('detail', ''))[:200]}",
        })
    return payload


def publish(run_dir: Path, url: str, user: str, password: str, dry_run: bool) -> dict:
    annotations = payloads(run_dir)
    results = []
    auth = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    for annotation in annotations:
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
        "annotationCount": len(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--grafana-url", default=os.environ.get("GRAFANA_URL", "http://127.0.0.1:3001"))
    parser.add_argument("--user", default=os.environ.get("GRAFANA_ADMIN_USER", ""))
    parser.add_argument("--password", default=os.environ.get("GRAFANA_ADMIN_PASSWORD", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and (not args.user or not args.password):
        print("[grafana] --user/--password or GRAFANA_ADMIN_* are required", file=sys.stderr)
        return 2
    try:
        result = publish(args.run_dir.resolve(), args.grafana_url, args.user, args.password, args.dry_run)
    except (OSError, KeyError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        print(f"[grafana] ERROR: {error}", file=sys.stderr)
        return 1
    output = args.run_dir / "grafana-annotations.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[grafana] annotations={result['annotationCount']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
