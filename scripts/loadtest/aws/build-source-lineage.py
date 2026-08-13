#!/usr/bin/env python3
"""Build a no-rerun source-lineage contract outside existing evidence.

The command reads the existing B-01/D-006 inputs and the two Git revisions,
then writes one new control artifact.  It never rewrites the B-01 evidence
root and refuses a destination that already exists or is protected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from source_lineage import (
        SourceLineageError,
        assert_new_output_path,
        build_lineage,
        read_json,
        require_commit,
        sha256_file,
        validate_lineage,
    )
except ImportError:  # pragma: no cover - direct external invocation
    from scripts.loadtest.aws.source_lineage import (
        SourceLineageError,
        assert_new_output_path,
        build_lineage,
        read_json,
        require_commit,
        sha256_file,
        validate_lineage,
    )

try:
    from slo_contract import verify_input_digest_manifest
except ImportError:  # pragma: no cover - direct external invocation
    from scripts.loadtest.aws.slo_contract import verify_input_digest_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--b01-run-id", required=True)
    parser.add_argument("--d005-rate-file", type=Path, required=True)
    parser.add_argument("--freeze-metadata", type=Path, required=True)
    parser.add_argument("--b01-profile", type=Path, required=True)
    parser.add_argument("--baseline-candidate", type=Path, required=True)
    parser.add_argument("--protected-manifest", type=Path, required=True)
    parser.add_argument("--measurement-source-sha", required=True)
    parser.add_argument("--controller-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repository_root.resolve()
    measurement_sha = require_commit(args.measurement_source_sha, "measurementSourceCommitSha")
    controller_sha = require_commit(args.controller_source_sha, "controllerSourceCommitSha")
    d005 = read_json(args.d005_rate_file.resolve(), "D-005 rate record")
    freeze = read_json(args.freeze_metadata.resolve(), "D-006 freeze metadata")
    profile_sha = sha256_file(args.b01_profile.resolve())
    candidate_sha = sha256_file(args.baseline_candidate.resolve())
    d005_sha = sha256_file(args.d005_rate_file.resolve())
    manifest_ref = freeze.get("freezeInputManifest")
    if not isinstance(manifest_ref, str) or Path(manifest_ref).is_absolute():
        raise SourceLineageError("D-006 freezeInputManifest must be a relative path")
    freeze_manifest = (args.freeze_metadata.resolve().parent / manifest_ref).resolve()
    if not freeze_manifest.is_file():
        raise SourceLineageError("D-006 freezeInputManifest does not exist")
    freeze_input_manifest = read_json(freeze_manifest, "D-006 freeze input manifest")
    try:
        verify_input_digest_manifest(
            freeze_input_manifest,
            contract_path=root / "load-tests/aws/contracts/slo-v1.0.json",
        )
    except ValueError as error:
        raise SourceLineageError(str(error)) from error
    if freeze_input_manifest.get("runId") != args.b01_run_id:
        raise SourceLineageError("D-006 freeze input manifest runId does not match B-01 runId")
    if freeze.get("freezeInputDigest") != freeze_input_manifest.get("inputDigest"):
        raise SourceLineageError("D-006 freezeInputDigest does not match freeze input manifest")
    freeze_input_digest = freeze.get("freezeInputDigest")
    if not isinstance(freeze_input_digest, str) or len(freeze_input_digest) != 64:
        raise SourceLineageError("D-006 freezeInputDigest is missing")
    payload = build_lineage(
        repository_root=root,
        b01_run_id=args.b01_run_id,
        measurement_sha=measurement_sha,
        controller_sha=controller_sha,
        d005=d005,
        freeze=freeze,
        b01_profile_sha=profile_sha,
        baseline_candidate_sha=candidate_sha,
        d005_rate_sha=d005_sha,
        freeze_input_digest=freeze_input_digest,
        protected_manifest=args.protected_manifest.resolve(),
    )
    validate_lineage(
        payload,
        repository_root=root,
        expected_controller_sha=controller_sha,
        expected_run_id=args.b01_run_id,
        expected_protected_manifest=args.protected_manifest.resolve(),
        expected_inputs={
            "b01ProfileSha256": profile_sha,
            "baselineCandidateSha256": candidate_sha,
            "d005RateRecordSha256": d005_sha,
            "freezeInputDigest": freeze_input_digest,
        },
        require_clean_worktree=True,
    )
    destination = assert_new_output_path(
        args.output.resolve(),
        repository_root=root,
        protected_manifest=args.protected_manifest.resolve(),
    )
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if not args.dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
        except FileExistsError as error:
            raise SourceLineageError("source lineage output was created concurrently") from error
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, SourceLineageError, ValueError, json.JSONDecodeError) as error:
        print(f"[source-lineage] ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
