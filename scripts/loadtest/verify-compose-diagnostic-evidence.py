#!/usr/bin/env python3
"""Fail-closed safety and completeness check for SCRUM-41 evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SECRET_FIELD = re.compile(r"(?i)(refreshToken|accessToken|password|clientSecret|privateKey|authorization|cookie)")
TOKEN_VALUE = re.compile(r"(?i)(bearer\s+[A-Za-z0-9._-]{24,}|refresh_token\s*=\s*[A-Za-z0-9_-]{32,})")


class EvidenceError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--require-captures", action="store_true")
    return parser.parse_args()


def inspect_value(value: object, path: str, findings: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_FIELD.search(str(key)):
                findings.append(f"secret-like field: {path}.{key}")
            inspect_value(child, f"{path}.{key}", findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            inspect_value(child, f"{path}[{index}]", findings)
    elif isinstance(value, str) and TOKEN_VALUE.search(value):
        findings.append(f"secret-like value: {path}")


def verify(evidence_root: Path, require_captures: bool) -> dict[str, object]:
    if not evidence_root.is_dir():
        raise EvidenceError(f"evidence directory does not exist: {evidence_root}")
    findings: list[str] = []
    checked = 0
    for path in sorted(evidence_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = str(path.relative_to(evidence_root))
        if path.name == "credentials.json" or "token" in path.name.lower() and path.suffix not in {".jsonl", ".log"}:
            findings.append(f"credential-like file name: {relative}")
        checked += 1
        if path.suffix.lower() == ".json" and path.name != "raw.json":
            try:
                inspect_value(json.loads(path.read_text(encoding="utf-8")), relative, findings)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                findings.append(f"invalid JSON: {relative}: {error.__class__.__name__}")
        elif path.suffix.lower() in {".log", ".jsonl", ".md", ".txt"}:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if TOKEN_VALUE.search(content):
                findings.append(f"secret-like text: {relative}")
    required = ["campaign-metadata.json", "campaign-manifest.json", "summary.json", "verdict.json"]
    missing = [name for name in required if not (evidence_root / name).is_file()]
    if missing:
        findings.append(f"missing required evidence: {','.join(missing)}")
    if require_captures:
        root_capture = evidence_root / "grafana" / "capture-status.json"
        replicate_dirs = sorted(
            path for path in evidence_root.glob("replicate-*") if path.is_dir()
        )
        capture_statuses = (
            [root_capture]
            if root_capture.is_file()
            else [path / "grafana" / "capture-status.json" for path in replicate_dirs]
        )
        if not capture_statuses:
            findings.append("Grafana capture-status.json is missing")
        elif replicate_dirs and len(capture_statuses) != len(replicate_dirs):
            findings.append("Grafana capture-status.json is missing for one or more replicates")
        for capture_status in capture_statuses:
            if not capture_status.is_file():
                findings.append(
                    f"Grafana capture-status.json is missing: {capture_status.relative_to(evidence_root)}"
                )
                continue
            try:
                status = json.loads(capture_status.read_text(encoding="utf-8"))
                if status.get("status") != "captured":
                    findings.append(
                        f"Grafana capture status is not captured: {capture_status.relative_to(evidence_root)}"
                    )
            except json.JSONDecodeError:
                findings.append(
                    f"Grafana capture-status.json is invalid: {capture_status.relative_to(evidence_root)}"
                )
    report = {
        "schemaVersion": "compose-diagnostic-evidence-safety/v1",
        "checkedFiles": checked,
        "status": "pass" if not findings else "fail",
        "findings": findings,
        "generatedAtUtc": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
    }
    (evidence_root / "evidence-safety.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if findings:
        raise EvidenceError("evidence safety check failed: " + findings[0])
    return report


def main() -> int:
    args = parse_args()
    try:
        report = verify(args.evidence_root.resolve(), args.require_captures)
    except EvidenceError as error:
        print(f"[diagnostic-safety] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "checkedFiles": report["checkedFiles"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
