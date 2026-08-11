#!/usr/bin/env python3
"""Build a checksum manifest, run the safety scan, and upload a local AWS
load-test evidence bundle to its S3 prefix.

This is the upload direction of contracts/EVIDENCE_BUNDLE_CONTRACT.md.
aws-load-test-handoff/plans/05_EVIDENCE_EXPORT_PLAN.md covers the opposite
direction (S3/Grafana -> local, for report-writing); the two share the bundle
layout and manifest format but are separate scripts, since they run at
different times on different sides (this one on the Runner right after a
test; Plan05's tooling later on an operator's machine).

03_AWS_B01_EXECUTION_PLAN.md's execution step "safety scan 후 Evidence S3
업로드" calls this script as a black box; it does not reimplement any of
this logic.

Reuses scripts/loadtest/verify-evidence-safety.py's scan() function directly
(dynamic import, not a subprocess) instead of duplicating the secret-pattern
scan. Upload is refused if the scan finds anything.

Every file is uploaded with `aws s3api put-object --checksum-algorithm
SHA256`; the response's ChecksumSHA256 is compared against a checksum
computed locally immediately before that upload (not just the value recorded
in manifest.json earlier), so a file that changed between manifest build and
upload is caught rather than silently trusted.

Account safety: gated by the same --expected-account-id/sts pattern as
seed-aws-load-data.py and cleanup-aws-load-data.py
(aws-load-test-handoff/contracts/RUN_METADATA_CONTRACT.md). Full Account
IDs, Secrets, and credentials never appear in stdout, manifest.json, or
evidence-safety.json.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,40}$")
ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")
MANIFEST_FILENAME = "manifest.json"
SAFETY_REPORT_FILENAME = "evidence-safety.json"
SKIP_FILENAMES = {MANIFEST_FILENAME}


class UploadError(RuntimeError):
    """A sanitized upload or contract verification failure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="RUN_METADATA_CONTRACT runId; must match evidence-root/metadata.json's runId if that file exists")
    parser.add_argument("--evidence-root", type=Path, required=True, help="Local evidence bundle directory, e.g. /var/lib/travel-planner/load-test-evidence/<run-id>")
    parser.add_argument("--data-file", type=Path, required=True, help="seed-aws-load-data.py's credential file, passed to the safety scanner")
    parser.add_argument("--expected-account-id", required=True, help="12-digit AWS account ID this run is approved to target")
    parser.add_argument("--region", required=True)
    parser.add_argument("--s3-bucket", required=True)
    parser.add_argument("--s3-prefix", default="evidence/aws-load-tests", help="Bucket prefix before <run-id>/ (matches infra/modules/load_test_runner's evidence_prefix)")
    parser.add_argument("--dry-run", action="store_true", help="Build manifest.json and run the safety scan, but do not upload anything")
    return parser.parse_args()


def run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()[-1:] or ["command failed"]
        raise UploadError(f"command failed ({completed.returncode}): {' '.join(command[:3])}; {detail[0]}")
    return completed.stdout


def verify_account(expected_account_id: str, region: str) -> None:
    if not ACCOUNT_ID_PATTERN.fullmatch(expected_account_id):
        raise UploadError("--expected-account-id must be exactly 12 digits")
    completed = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--region", region, "--query", "Account", "--output", "text"],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise UploadError("sts:GetCallerIdentity failed; cannot verify the target AWS account")
    if completed.stdout.strip() != expected_account_id:
        raise UploadError("observed AWS account does not match --expected-account-id; refusing to run")


def load_safety_scanner():
    script_path = Path(__file__).resolve().parents[1] / "verify-evidence-safety.py"
    spec = importlib.util.spec_from_file_location("verify_evidence_safety", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def check_metadata_run_id(evidence_root: Path, run_id: str) -> None:
    metadata_path = evidence_root / "metadata.json"
    if not metadata_path.exists():
        return
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UploadError("evidence-root/metadata.json is not valid JSON") from error
    metadata_run_id = metadata.get("runId")
    if metadata_run_id is not None and metadata_run_id != run_id:
        raise UploadError("evidence-root/metadata.json runId does not match --run-id; refusing to upload")


def sha256_of_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def hex_to_base64(hex_digest: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


def iter_bundle_files(evidence_root: Path):
    for path in sorted(evidence_root.rglob("*")):
        if not path.is_file() or path.name in SKIP_FILENAMES:
            continue
        yield path


def build_manifest(evidence_root: Path, run_id: str) -> dict:
    files = []
    for path in iter_bundle_files(evidence_root):
        sha256_hex, size = sha256_of_file(path)
        files.append({
            "path": str(path.relative_to(evidence_root)),
            "sha256": sha256_hex,
            "bytes": size,
        })
    return {
        "runId": run_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(files),
        "files": files,
    }


def run_safety_scan(safety_module, evidence_root: Path, data_file: Path) -> dict:
    result = safety_module.scan(evidence_root, data_file)
    output_path = evidence_root / SAFETY_REPORT_FILENAME
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def upload_file(bucket: str, key: str, local_path: Path, expected_sha256_hex: str) -> None:
    output = run([
        "aws", "s3api", "put-object",
        "--bucket", bucket, "--key", key, "--body", str(local_path),
        "--checksum-algorithm", "SHA256",
    ])
    try:
        response = json.loads(output)
    except json.JSONDecodeError as error:
        raise UploadError(f"S3 put-object returned unparseable output for {key}") from error
    remote_checksum = response.get("ChecksumSHA256")
    if not remote_checksum:
        raise UploadError(f"S3 did not return a SHA256 checksum for {key}")
    if remote_checksum != hex_to_base64(expected_sha256_hex):
        raise UploadError(f"checksum mismatch after upload: {key}")


def upload_bundle(evidence_root: Path, run_id: str, bucket: str, s3_prefix: str, manifest: dict) -> int:
    manifest_by_path = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    uploaded = 0
    for path in iter_bundle_files(evidence_root):
        relative_path = str(path.relative_to(evidence_root))
        fresh_sha256_hex, _ = sha256_of_file(path)
        recorded_sha256_hex = manifest_by_path.get(relative_path)
        if recorded_sha256_hex is not None and recorded_sha256_hex != fresh_sha256_hex:
            raise UploadError(f"{relative_path} changed after manifest.json was built; refusing to upload")
        key = f"{s3_prefix}/{run_id}/{relative_path}"
        upload_file(bucket, key, path, fresh_sha256_hex)
        uploaded += 1
    # manifest.json itself, last, so a failed upload never leaves an orphaned
    # manifest claiming files exist that didn't actually make it to S3.
    manifest_path = evidence_root / MANIFEST_FILENAME
    manifest_sha256_hex, _ = sha256_of_file(manifest_path)
    upload_file(bucket, f"{s3_prefix}/{run_id}/{MANIFEST_FILENAME}", manifest_path, manifest_sha256_hex)
    uploaded += 1
    return uploaded


def main() -> int:
    args = parse_args()
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise UploadError("--run-id must be 1-40 chars of [A-Za-z0-9-]")
    evidence_root = args.evidence_root.resolve()
    if not evidence_root.is_dir():
        raise UploadError("--evidence-root does not exist or is not a directory")
    data_file = args.data_file.resolve()
    if not data_file.exists():
        raise UploadError("--data-file does not exist")

    check_metadata_run_id(evidence_root, args.run_id)
    verify_account(args.expected_account_id, args.region)

    safety_module = load_safety_scanner()
    safety_result = run_safety_scan(safety_module, evidence_root, data_file)
    if not safety_result.get("safe"):
        raise UploadError(
            f"safety scan found {safety_result.get('findingCount')} finding(s) in "
            f"{safety_result.get('scannedFiles')} file(s); refusing to upload"
        )
    print(f"[upload] safety scan clean: {safety_result.get('scannedFiles')} file(s) scanned")

    manifest = build_manifest(evidence_root, args.run_id)
    manifest_path = evidence_root / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[upload] manifest.json written: {manifest['fileCount']} file(s)")

    if args.dry_run:
        print("[upload] dry-run: no files uploaded")
        return 0

    uploaded = upload_bundle(evidence_root, args.run_id, args.s3_bucket, args.s3_prefix, manifest)
    print(f"[upload] complete: {uploaded} file(s) uploaded and checksum-verified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UploadError as error:
        print(f"[upload] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
