#!/usr/bin/env python3
"""Check load-test evidence for credentials, cookies, and synthetic PII."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


FORBIDDEN_PATTERNS = {
    "authorization_header": re.compile(r"\bAuthorization\s*[:=]", re.IGNORECASE),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE),
    "cookie_header": re.compile(r"\bCookie\s*[:=]", re.IGNORECASE),
    "refresh_cookie": re.compile(r"refresh_token\s*=", re.IGNORECASE),
    "synthetic_email": re.compile(r"[A-Za-z0-9._%+-]+@loadtest\.local", re.IGNORECASE),
}


def load_secret_values(data_file: Path) -> set[str]:
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    values: set[str] = set()
    for credential in payload.get("credentials", []):
        for key in ("accessToken", "refreshToken", "refreshFamilyId", "userId"):
            value = credential.get(key)
            if isinstance(value, str) and len(value) >= 8:
                values.add(value)
    return values


def scan(evidence_root: Path, data_file: Path) -> dict:
    secret_values = load_secret_values(data_file)
    findings = []
    scanned_files = 0
    for path in sorted(evidence_root.rglob("*")):
        # data.json is the seed script's own raw credential file (its accessToken/
        # refreshToken/etc. ARE the secret_values above) — scanning it against
        # itself would always "find" its own contents. It must never be part of
        # the evidence bundle in the first place (see upload-aws-evidence.py's
        # SKIP_FILENAMES); this skip is a second line of defense, not a
        # substitute for keeping it out of evidence_root.
        if not path.is_file() or path.name in {"evidence-safety.json", "gate-report.json", "data.json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned_files += 1
        for name, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                findings.append({"file": str(path), "type": name})
        for secret in secret_values:
            if secret in text:
                findings.append({"file": str(path), "type": "credential-value"})
                break
    return {
        "evidenceRoot": str(evidence_root),
        "scannedFiles": scanned_files,
        "findingCount": len(findings),
        "findings": findings,
        "safe": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--data-file", type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.evidence_root.resolve(), args.data_file.resolve())
    output = args.evidence_root / "evidence-safety.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if result["safe"]:
        print(f"[safety] safe: scanned {result['scannedFiles']} files")
        return 0
    print(f"[safety] ERROR: {result['findingCount']} finding(s); see {output}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
