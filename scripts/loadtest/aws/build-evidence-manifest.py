#!/usr/bin/env python3
"""Finalize a downloaded local AWS load-test evidence bundle: run the safety
scan, build manifest.json (SHA-256 + byte size per file, tagged by origin),
and optionally cross-check local file checksums against the S3 objects they
were downloaded from.

This is the local-side counterpart to scripts/loadtest/aws/upload-aws-evidence.py
(which builds/uploads a manifest from the Runner right after a test), per
aws-load-test-handoff/plans/05_EVIDENCE_EXPORT_PLAN.md. It runs later, after
download-aws-evidence.sh has pulled the bundle from S3 and (optionally)
scripts/loadtest/aws/export-grafana-evidence.py has added grafana/* files
that were never uploaded (they're generated locally, after the fact). The two
scripts intentionally share the manifest.json shape but are not merged, since
they run at different times on different sides of the pipeline (see
upload-aws-evidence.py's docstring).

Reuses scripts/loadtest/verify-evidence-safety.py's scan() function directly
(dynamic import, same pattern as upload-aws-evidence.py) instead of
duplicating the secret-pattern scan.

Every file's origin is recorded so original (S3-downloaded, produced during
the AWS run) and derived (Grafana-exported or locally-generated) material are
distinguishable in the manifest, per contracts/EVIDENCE_BUNDLE_CONTRACT.md.
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
MANIFEST_FILENAME = "manifest.json"
SAFETY_REPORT_FILENAME = "evidence-safety.json"
SKIP_FILENAMES = {MANIFEST_FILENAME}
DEFAULT_PNG_STATUS_REASON = "D-003 requires SSM port-forward plus read-only browser capture; Query JSON remains the evidence of record until every contracted panel PNG is saved."


class ManifestError(RuntimeError):
    """A sanitized manifest-build or checksum-comparison failure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True, help="Local evidence bundle directory, e.g. evidence/aws-load-tests/<run-id>")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-file", type=Path, default=None, help="Runner-side seed credential file; omit after data.json has been retired")
    parser.add_argument("--require-png", action="store_true", help="Fail unless every Grafana capture contract has a matching panel PNG")
    parser.add_argument("--compare-s3-bucket", default="", help="If given, cross-check s3-download-sourced files' checksums against this bucket via s3api get-object-attributes")
    parser.add_argument("--s3-prefix", default="evidence/aws-load-tests", help="Bucket prefix before <run-id>/ (matches upload-aws-evidence.py's default)")
    parser.add_argument("--region", default="", help="Required with --compare-s3-bucket")
    return parser.parse_args()


def run_command(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()[-1:] or ["command failed"]
        raise ManifestError(f"command failed ({completed.returncode}): {' '.join(command[:4])}; {detail[0]}")
    return completed.stdout


def load_safety_scanner():
    script_path = Path(__file__).resolve().parents[1] / "verify-evidence-safety.py"
    spec = importlib.util.spec_from_file_location("verify_evidence_safety", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run_safety_scan(safety_module, evidence_root: Path, data_file: Path) -> dict:
    result = safety_module.scan(evidence_root, data_file)
    output_path = evidence_root / SAFETY_REPORT_FILENAME
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


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


def classify_source(relative_path: str) -> str:
    # s3-download: uploaded during the AWS run, downloaded back verbatim.
    # grafana-export: produced locally, after the fact, by export-grafana-evidence.py.
    # generated-locally: produced by this script's own safety-scan step.
    if relative_path == SAFETY_REPORT_FILENAME:
        return "generated-locally"
    if relative_path.startswith("grafana/"):
        return "grafana-export"
    return "s3-download"


def determine_png_status(evidence_root: Path) -> dict:
    # D-003-R1 requires every captured panel-<id>.png to be linked to its
    # runId/fromUtc/toUtc/dashboardUid+version/Query JSON path
    # (TEAM_MEMBER_B01_ACTION_REQUEST.md 4.4). export-grafana-evidence.py
    # writes that link as panel-<id>.capture.json next to where the operator
    # is expected to save the PNG; a PNG without a matching contract file
    # fails that linkage requirement and is flagged rather than silently
    # counted as valid evidence.
    panels_dir = evidence_root / "grafana" / "panels"
    if not panels_dir.exists():
        return {"pngStatus": "not-exported", "pngStatusReason": DEFAULT_PNG_STATUS_REASON}

    png_panel_ids = {p.name.removeprefix("panel-").removesuffix(".png") for p in panels_dir.glob("panel-*.png")}
    contract_panel_ids = {p.name.removeprefix("panel-").removesuffix(".capture.json") for p in panels_dir.glob("panel-*.capture.json")}

    if not png_panel_ids:
        reason = DEFAULT_PNG_STATUS_REASON
        status_path = panels_dir / "status.json"
        if status_path.exists():
            try:
                reason = json.loads(status_path.read_text(encoding="utf-8")).get("reason", reason)
            except json.JSONDecodeError:
                pass
        return {
            "pngStatus": "not-exported",
            "pngStatusReason": reason,
            "pendingCaptureContracts": len(contract_panel_ids),
        }

    unlinked = sorted(png_panel_ids - contract_panel_ids, key=lambda panel_id: (len(panel_id), panel_id))
    result = {
        "pngStatus": "exported" if not unlinked else "exported-with-unlinked-files",
        "pngCount": len(png_panel_ids),
        "linkedPngCount": len(png_panel_ids) - len(unlinked),
    }
    if unlinked:
        result["unlinkedPanelIds"] = unlinked
        result["pngStatusReason"] = (
            "Every captured panel-<id>.png must have a matching panel-<id>.capture.json "
            "(runId/fromUtc/toUtc/dashboardUid+version/Query JSON path) per "
            "TEAM_MEMBER_B01_ACTION_REQUEST.md section 4.4; these PNGs do not."
        )
    return result


def build_manifest(evidence_root: Path, run_id: str) -> dict:
    files = []
    for path in iter_bundle_files(evidence_root):
        sha256_hex, size = sha256_of_file(path)
        relative_path = str(path.relative_to(evidence_root))
        files.append({
            "path": relative_path,
            "sha256": sha256_hex,
            "bytes": size,
            "source": classify_source(relative_path),
        })
    manifest = {
        "runId": run_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(files),
        "files": files,
    }
    manifest.update(determine_png_status(evidence_root))
    return manifest


def get_s3_checksum_base64(bucket: str, key: str, region: str) -> str:
    output = run_command([
        "aws", "s3api", "get-object-attributes",
        "--bucket", bucket, "--key", key,
        "--object-attributes", "Checksum",
        "--region", region, "--output", "json",
    ])
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise ManifestError(f"S3 get-object-attributes returned unparseable output for {key}") from error
    checksum = payload.get("Checksum", {}).get("ChecksumSHA256")
    if not checksum:
        raise ManifestError(f"S3 object has no recorded SHA256 checksum: {key}")
    return checksum


def compare_with_s3(run_id: str, bucket: str, s3_prefix: str, region: str, s3_sourced_files: list[dict]) -> dict:
    comparisons = []
    all_match = True
    for entry in s3_sourced_files:
        key = f"{s3_prefix}/{run_id}/{entry['path']}"
        local_checksum_b64 = hex_to_base64(entry["sha256"])
        try:
            remote_checksum_b64 = get_s3_checksum_base64(bucket, key, region)
            matches = remote_checksum_b64 == local_checksum_b64
        except ManifestError as error:
            matches = False
            comparisons.append({"path": entry["path"], "matches": False, "detail": str(error)})
            all_match = False
            continue
        comparisons.append({"path": entry["path"], "matches": matches})
        if not matches:
            all_match = False
    return {"compared": True, "allMatch": all_match, "files": comparisons}


def main() -> int:
    args = parse_args()
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ManifestError("--run-id must be 1-40 chars of [A-Za-z0-9-]")
    evidence_root = args.evidence_root.resolve()
    if not evidence_root.is_dir():
        raise ManifestError("--evidence-root does not exist or is not a directory")
    data_file = args.data_file.resolve() if args.data_file else None
    if data_file is not None and not data_file.exists():
        raise ManifestError("--data-file does not exist")
    if args.compare_s3_bucket and not args.region:
        raise ManifestError("--region is required with --compare-s3-bucket")

    safety_module = load_safety_scanner()
    safety_result = run_safety_scan(safety_module, evidence_root, data_file)
    if not safety_result.get("safe"):
        raise ManifestError(
            f"safety scan found {safety_result.get('findingCount')} finding(s) in "
            f"{safety_result.get('scannedFiles')} file(s); refusing to finalize manifest.json"
        )
    print(f"[manifest] safety scan clean: {safety_result.get('scannedFiles')} file(s) scanned")

    manifest = build_manifest(evidence_root, args.run_id)

    if args.require_png and manifest.get("pngStatus") != "exported":
        raise ManifestError(
            f"--require-png requested but pngStatus={manifest.get('pngStatus')}; capture every contracted panel before finalizing local export"
        )

    checksum_mismatch = False
    if args.compare_s3_bucket:
        s3_sourced_files = [entry for entry in manifest["files"] if entry["source"] == "s3-download"]
        comparison = compare_with_s3(args.run_id, args.compare_s3_bucket, args.s3_prefix, args.region, s3_sourced_files)
        manifest["s3ChecksumComparison"] = comparison
        if not comparison["allMatch"]:
            checksum_mismatch = True
            print("[manifest] WARNING: one or more local files do not match their S3 checksum", file=sys.stderr)

    manifest_path = evidence_root / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[manifest] manifest.json written: {manifest['fileCount']} file(s), pngStatus={manifest['pngStatus']}")

    return 1 if checksum_mismatch else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ManifestError as error:
        print(f"[manifest] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
