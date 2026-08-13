#!/usr/bin/env python3
"""Run the fixed Compose Gate profile three times plus one diagnostic spike."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[2]
DEFAULT_PROFILE = REPOSITORY_ROOT / "load-tests/gate-profile.json"
REHEARSAL_SCRIPT = REPOSITORY_ROOT / "scripts/loadtest/run-compose-rehearsal.sh"
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence/load-tests"


def utc_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def command_for(profile: dict, mode: str, run_id: str, project_name: str, env_file: Path) -> list[str]:
    command = [
        str(REHEARSAL_SCRIPT),
        mode,
        "--env-file", str(env_file),
        "--run-id", run_id,
        "--project-name", project_name,
        "--users", str(profile["users"]),
        "--rate", str(profile["rate"]),
        "--baseline-duration", profile["baselineDuration"],
        "--recovery-duration", profile["recoveryDuration"],
        "--warmup", profile["warmup"],
        "--drill-at-min", str(profile["drillAtMin"]),
        "--drill-mode", profile["drillMode"],
        "--spike-peak-rate", str(profile["spikePeakRate"]),
        "--spike-hold", profile["spikeHold"],
    ]
    return command


def run_gate(profile: dict, env_file: Path, cycles: int, gate_id: str) -> dict:
    manifest_path = EVIDENCE_ROOT / f"{gate_id}-gate-manifest.json"
    manifest = {
        "gateId": gate_id,
        "status": "running",
        "startedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "profile": profile,
        "runs": [],
    }
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    write_manifest(manifest_path, manifest)
    run_env = os.environ.copy()
    run_env["K6_IMAGE"] = profile["k6Image"]
    try:
        for cycle in range(1, cycles + 1):
            run_id = f"{gate_id}-c{cycle}"
            project_name = f"travel-planner-rehearsal-{run_id}"
            subprocess.run(command_for(profile, "all", run_id, project_name, env_file), check=True, cwd=REPOSITORY_ROOT, env=run_env)
            manifest["runs"].append({
                "cycle": cycle,
                "runId": run_id,
                "scenarios": [
                    str(EVIDENCE_ROOT / f"{run_id}-smoke-smoke"),
                    str(EVIDENCE_ROOT / f"{run_id}-baseline-baseline"),
                    str(EVIDENCE_ROOT / f"{run_id}-recovery-recovery-steady"),
                ],
            })
            write_manifest(manifest_path, manifest)

        spike_id = f"{gate_id}-spike"
        spike_project = f"travel-planner-rehearsal-{spike_id}"
        subprocess.run(command_for(profile, "spike", spike_id, spike_project, env_file), check=True, cwd=REPOSITORY_ROOT, env=run_env)
        manifest["runs"].append({
            "type": "spike",
            "runId": spike_id,
            "scenarios": [str(EVIDENCE_ROOT / f"{spike_id}-spike-spike")],
        })
        manifest["status"] = "completed"
        manifest["finishedAtUtc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        write_manifest(manifest_path, manifest)
        return manifest
    except (OSError, subprocess.CalledProcessError) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        manifest["finishedAtUtc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        write_manifest(manifest_path, manifest)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--env-file", type=Path, default=REPOSITORY_ROOT / ".env.prod.example")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--gate-id", default=None)
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("--cycles must be at least 1")
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    gate_id = args.gate_id or f"compose-gate-{utc_id()}"
    try:
        manifest = run_gate(profile, args.env_file.resolve(), args.cycles, gate_id)
    except (OSError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"[gate] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"gateId": manifest["gateId"], "status": manifest["status"], "runs": len(manifest["runs"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
