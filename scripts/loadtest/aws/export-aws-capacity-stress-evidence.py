#!/usr/bin/env python3
"""Build a privacy-safe checksum manifest for Capacity/Scale Stress evidence.

The script only reads the supplied run directory and writes a derived manifest
there. Upload/download is intentionally left to the existing operator-gated
AWS evidence transfer path; this helper never receives or prints credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


SECRET_PATTERNS = (
    re.compile(r'''(?i)["']?\b(password|secret|token|authorization|access[_-]?key)["']?\s*[:=]\s*["']?[^,\s}\"']+'''),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
SKIP = {"capacity-evidence-manifest.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def privacy_findings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings = []
    privacy_failures = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(pattern.pattern)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        parser.error(f"run directory does not exist: {run_dir}")
    files = []
    findings = []
    privacy_failures = []
    for path in sorted(item for item in run_dir.rglob("*") if item.is_file() and item.name not in SKIP):
        relative = path.relative_to(run_dir).as_posix()
        if relative.endswith("/data.json") or relative == "data.json":
            findings.append({"path": relative, "reason": "credential fixture is excluded from export"})
            continue
        patterns = privacy_findings(path)
        if patterns:
            findings.append({"path": relative, "reason": "sensitive pattern detected"})
            privacy_failures.append(relative)
            continue
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path), "origin": "capacity-stress-run"})
    payload = {
        "schemaVersion": "capacity-stress-evidence-manifest/v1",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "runDir": str(run_dir),
        "files": files,
        "excluded": findings,
        # Excluding the run-scoped credential fixture is an expected privacy
        # control, not a failed scan. Only a detected secret in an otherwise
        # exportable artifact makes the scan fail.
        "privacyScan": "PASS" if not privacy_failures else "FAIL",
        "upload": "operator-gated existing AWS evidence transfer only",
    }
    output = run_dir / "capacity-evidence-manifest.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(output), "files": len(files), "excluded": len(findings), "privacyScan": payload["privacyScan"]}, sort_keys=True))
    return 0 if not privacy_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
