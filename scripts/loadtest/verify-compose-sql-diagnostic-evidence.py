#!/usr/bin/env python3
"""Fail-closed completeness and secret/UUID scan for SCRUM-41 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


UUID_PATTERN = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"(?i)\b(?:bearer\s+[a-z0-9._-]{20,}|refresh_token\s*=\s*[a-z0-9_-]{20,})")
SECRET_KEY_PATTERN = re.compile(r"(?i)(access.?token|refresh.?token|password|authorization|cookie|client.?secret|private.?key|jwt)")
LITERAL_QUERY_PATTERN = re.compile(r"(?is)\b(?:where|values|set)\b[^\n]{0,160}(?:'[0-9a-f-]{8,}'|\b\d{7,}\b)")


class EvidenceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_value(value: object, relative: str, findings: list[dict[str, str]], path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if SECRET_KEY_PATTERN.search(key_text):
                findings.append({"file": relative, "type": "secret-like-field", "path": f"{path}.{key_text}"})
            inspect_value(child, relative, findings, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            inspect_value(child, relative, findings, f"{path}[{index}]")
    elif isinstance(value, str):
        if TOKEN_PATTERN.search(value):
            findings.append({"file": relative, "type": "token-like-value", "path": path})
        if UUID_PATTERN.search(value):
            findings.append({"file": relative, "type": "synthetic-uuid", "path": path})
        if LITERAL_QUERY_PATTERN.search(value) and "normalized" not in path.lower():
            findings.append({"file": relative, "type": "literal-query", "path": path})


def verify(root: Path, require_analysis: bool = False, require_captures: bool = False) -> dict[str, object]:
    if not root.is_dir():
        raise EvidenceError(f"evidence directory does not exist: {root}")
    findings: list[dict[str, str]] = []
    checked = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == "evidence-safety.json":
            continue
        relative = str(path.relative_to(root))
        if path.name in {"credentials.json", "data.json"} or "token" in path.name.lower():
            findings.append({"file": relative, "type": "credential-like-file"})
        checked += 1
        if path.suffix.lower() == ".json":
            try:
                inspect_value(load_json(path), relative, findings)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                findings.append({"file": relative, "type": "invalid-json"})
        elif path.suffix.lower() in {".jsonl", ".log", ".md", ".txt"}:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if TOKEN_PATTERN.search(content) or UUID_PATTERN.search(content):
                findings.append({"file": relative, "type": "secret-or-uuid-like-text"})
    required = ["campaign-metadata.json", "campaign-manifest.json", "evidence-safety.json"] if require_analysis else ["campaign-metadata.json", "campaign-manifest.json"]
    if require_analysis:
        required.extend(["summary.json", "verdict.json", "SQL_DIAGNOSTIC_REPORT.md", "closure-audit.json"])
    for name in required:
        if not (root / name).is_file() and name != "evidence-safety.json":
            findings.append({"file": name, "type": "missing-required-evidence"})
    replicate_dirs = sorted(path for path in root.glob("replicate-*") if path.is_dir())
    if not replicate_dirs:
        findings.append({"file": ".", "type": "no-replicate-directory"})
    for replicate in replicate_dirs:
        for name in ("replicate-metadata.json", "fixture-manifest.json", "service-stats.jsonl", "metric-inventory.json"):
            if not (replicate / name).is_file():
                findings.append({"file": str((replicate / name).relative_to(root)), "type": "missing-replicate-evidence"})
        stages = sorted(path for path in (replicate / "stages").glob("*-*") if path.is_dir())
        if not stages:
            findings.append({"file": str((replicate / "stages").relative_to(root)), "type": "missing-stages"})
        for stage in stages:
            for name in ("metadata.json", "operations.jsonl", "raw.json", "k6-native-summary.json", "run-status.json", "pg-stat-statements.json", "query-breakdown.json", "backend-metric-delta.json"):
                if not (stage / name).is_file():
                    findings.append({"file": str((stage / name).relative_to(root)), "type": "missing-stage-evidence"})
            try:
                stats = load_json(stage / "pg-stat-statements.json")
                if isinstance(stats, dict) and int(stats.get("unknownCount", 0)) != 0:
                    findings.append({"file": str((stage / "pg-stat-statements.json").relative_to(root)), "type": "unknown-sql-family"})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
        if require_captures:
            capture = replicate / "grafana" / "capture-status.json"
            if not capture.is_file():
                findings.append({"file": str(capture.relative_to(root)), "type": "missing-grafana-capture"})
            else:
                try:
                    status = load_json(capture)
                    if not isinstance(status, dict) or status.get("status") != "captured":
                        findings.append({"file": str(capture.relative_to(root)), "type": "invalid-grafana-capture-status"})
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    findings.append({"file": str(capture.relative_to(root)), "type": "invalid-grafana-capture-json"})
    manifest_path = root / "campaign-manifest.json"
    if manifest_path.is_file():
        try:
            manifest = load_json(manifest_path)
            if isinstance(manifest, dict):
                digests = manifest.get("sourceDigests", {})
                if not isinstance(digests, dict) or not digests:
                    findings.append({"file": "campaign-manifest.json", "type": "missing-source-digests"})
                source_hashes = {str(value) for value in digests.values() if isinstance(value, str)}
                for path in sorted(root.glob("replicate-*/replicate-metadata.json")):
                    payload = load_json(path)
                    if isinstance(payload, dict) and source_hashes and not source_hashes.issubset({str(value) for value in (payload.get("sourceDigests") or {}).values()}):
                        findings.append({"file": str(path.relative_to(root)), "type": "source-digest-drift"})
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            findings.append({"file": "campaign-manifest.json", "type": "invalid-manifest"})
    report = {
        "schemaVersion": "scrum41-sql-diagnostic-evidence-safety/v1",
        "generatedAtUtc": utc_now(),
        "evidenceRoot": str(root),
        "checkedFiles": checked,
        "findingCount": len(findings),
        "status": "pass" if not findings else "fail",
        "findings": findings,
    }
    (root / "evidence-safety.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if findings:
        raise EvidenceError(f"evidence safety failed: {findings[0]}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--require-analysis", action="store_true")
    parser.add_argument("--require-captures", action="store_true")
    args = parser.parse_args()
    try:
        report = verify(args.evidence_root.resolve(), args.require_analysis, args.require_captures)
    except (EvidenceError, OSError, json.JSONDecodeError) as error:
        print(f"[sql-evidence] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "checkedFiles": report["checkedFiles"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
