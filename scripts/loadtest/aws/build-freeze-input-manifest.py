#!/usr/bin/env python3
"""Build and verify the hash-bound inputs for a D-006 SLO freeze.

The manifest deliberately hashes only immutable inputs.  Its ``inputDigest``
is calculated from the canonical ``inputs`` object and therefore never
includes the manifest itself or freeze approval metadata; this avoids a
circular hash while allowing a Recovery evaluator to revalidate the freeze.
The command is local and side-effect limited to the requested output file.
It never calls AWS, Terraform, Grafana, or the credential seed/cleanup paths.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from slo_contract import CONTRACT_PATH, digest_json, load_contract, sha256_file, verify_input_digest_manifest
except ImportError:  # pragma: no cover - supports direct external invocation
    from scripts.loadtest.aws.slo_contract import CONTRACT_PATH, digest_json, load_contract, sha256_file, verify_input_digest_manifest


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MANIFEST_SCHEMA = "aws-d006-freeze-input-manifest-v1"


class FreezeInputError(ValueError):
    """A required D-006 input is absent, stale, or malformed."""


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FreezeInputError(f"{label} does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise FreezeInputError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise FreezeInputError(f"{label} must be a JSON object: {path}")
    return payload


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise FreezeInputError(f"{label} must be a lowercase SHA-256 digest")
    return value


def require_commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or not COMMIT_PATTERN.fullmatch(value):
        raise FreezeInputError(f"{label} must be a 40-character commit SHA")
    return value


def require_positive_rate(value: Any, label: str) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError) as error:
        raise FreezeInputError(f"{label} must be a positive finite number") from error
    if not math.isfinite(rate) or rate <= 0:
        raise FreezeInputError(f"{label} must be a positive finite number")
    return rate


def load_effective_spike(spike_run_dir: Path, b01_profile: Path) -> dict[str, Any]:
    metadata = read_json(spike_run_dir / "metadata.json", "Spike metadata")
    effective = metadata.get("effectiveInputs")
    if not isinstance(effective, dict):
        # B-01 Spike may have completed before Issue #302 added explicit
        # effectiveInputs metadata.  Derive the already-recorded peak from
        # the immutable stdout line and the profile's non-secret VU/hold
        # settings; this closes D-006 without rerunning Seed/Baseline/Spike.
        stdout_path = spike_run_dir / "stdout.log"
        try:
            stdout = stdout_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as error:
            raise FreezeInputError("Spike metadata has no effectiveInputs and stdout.log is unavailable") from error
        peak_matches = re.findall(r"Up to ([0-9]+(?:\.[0-9]+)?) iterations/s", stdout)
        if len(set(peak_matches)) != 1:
            raise FreezeInputError("legacy Spike stdout does not contain one unambiguous effective peak rate")
        profile = read_json(b01_profile, "B-01 profile")
        scenario_profile = profile.get("scenarios", {}).get("spike", {})
        if not isinstance(scenario_profile, dict):
            raise FreezeInputError("B-01 profile scenarios.spike is missing")
        legacy_baseline_rate = require_positive_rate(metadata.get("rate"), "legacy Spike metadata.rate")
        effective = {
            "scenario": "spike",
            "profileSha256": sha256_file(b01_profile),
            "classification": "diagnostic",
            "baselineRate": legacy_baseline_rate,
            "peakRateMultiplier": float(peak_matches[0]) / legacy_baseline_rate,
            "peakRate": float(peak_matches[0]),
            "hold": scenario_profile.get("hold"),
            "preAllocatedVUs": scenario_profile.get("preAllocatedVUs"),
            "maxVUs": scenario_profile.get("maxVUs"),
            "timeUnit": scenario_profile.get("timeUnit", "1s"),
            "provenance": "derived-from-legacy-spike-metadata-and-stdout",
        }
    if effective.get("scenario") != "spike":
        raise FreezeInputError("Spike effectiveInputs.scenario must be spike")
    if effective.get("classification") != "diagnostic":
        raise FreezeInputError("Spike effectiveInputs.classification must be diagnostic")
    profile_sha = require_sha(effective.get("profileSha256"), "Spike effectiveInputs.profileSha256")
    baseline_rate = require_positive_rate(effective.get("baselineRate"), "Spike effectiveInputs.baselineRate")
    peak_rate = require_positive_rate(effective.get("peakRate"), "Spike effectiveInputs.peakRate")
    multiplier = require_positive_rate(effective.get("peakRateMultiplier"), "Spike effectiveInputs.peakRateMultiplier")
    if multiplier <= 1 or not math.isclose(peak_rate, baseline_rate * multiplier, rel_tol=0, abs_tol=1e-9):
        raise FreezeInputError("Spike effective peakRate does not match baselineRate * peakRateMultiplier")
    if not isinstance(effective.get("hold"), str) or not effective["hold"].strip():
        raise FreezeInputError("Spike effectiveInputs.hold is missing")
    for field in ("preAllocatedVUs", "maxVUs"):
        value = effective.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise FreezeInputError(f"Spike effectiveInputs.{field} must be a positive integer")
    return effective


def build_manifest(
    *,
    run_id: str,
    source_sha: str,
    contract_path: Path,
    b01_profile: Path,
    baseline_candidate: Path,
    d005_rate_file: Path,
    spike_run_dir: Path,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id.strip():
        raise FreezeInputError("runId must be non-empty")
    source_sha = require_commit(source_sha, "sourceCommitSha")
    contract = load_contract(contract_path)
    b01_profile_sha = sha256_file(b01_profile)
    candidate_sha = sha256_file(baseline_candidate)
    d005_sha = sha256_file(d005_rate_file)
    d005 = read_json(d005_rate_file, "D-005 rate record")
    candidate = read_json(baseline_candidate, "Baseline candidate")
    effective_spike = load_effective_spike(spike_run_dir, b01_profile)

    if d005.get("sourceCommitSha") != source_sha:
        raise FreezeInputError("D-005 sourceCommitSha does not match the approved source SHA")
    if d005.get("profileSha256") != b01_profile_sha:
        raise FreezeInputError("D-005 profileSha256 does not match the B-01 profile")
    if d005.get("baselineCandidateSha256") != candidate_sha:
        raise FreezeInputError("D-005 baselineCandidateSha256 does not match the Baseline candidate")
    arrival_rate = require_positive_rate(d005.get("arrivalRate"), "D-005 arrivalRate")
    candidate_rate = candidate.get("confirmedRate")
    if candidate_rate is not None and not math.isclose(require_positive_rate(candidate_rate, "Baseline confirmedRate"), arrival_rate, rel_tol=0, abs_tol=1e-9):
        raise FreezeInputError("D-005 arrivalRate does not match Baseline confirmedRate")
    baseline_candidate = candidate.get("baselineCandidate")
    if candidate.get("passed") is not True or not isinstance(baseline_candidate, dict) or baseline_candidate.get("frozen") is not True:
        raise FreezeInputError("Baseline candidate is not a passed/frozen D-005 candidate")
    if effective_spike["profileSha256"] != b01_profile_sha:
        raise FreezeInputError("Spike profileSha256 does not match the B-01 profile")
    if not math.isclose(float(effective_spike["baselineRate"]), arrival_rate, rel_tol=0, abs_tol=1e-9):
        raise FreezeInputError("Spike baselineRate does not match D-005 arrivalRate")

    effective_spike_digest = digest_json(effective_spike)
    inputs = {
        "sourceCommitSha": source_sha,
        "b01ProfileSha256": b01_profile_sha,
        "baselineCandidateSha256": candidate_sha,
        "d005RateRecordSha256": d005_sha,
        "d005ArrivalRate": arrival_rate,
        "spikeEffectiveConfigSha256": effective_spike_digest,
    }
    return {
        "schemaVersion": MANIFEST_SCHEMA,
        "runId": run_id,
        "sloVersion": contract["sloVersion"],
        "contract": {
            "path": str(contract_path.resolve().relative_to(Path(__file__).resolve().parents[3])),
            "sha256": sha256_file(contract_path),
        },
        "inputs": inputs,
        "spike": {
            "classification": "diagnostic",
            "effectiveConfigSha256": effective_spike_digest,
            "effectiveConfig": effective_spike,
        },
        "inputDigest": digest_json(inputs),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def verify_manifest(manifest: dict[str, Any], *, contract_path: Path | None = None) -> bool:
    try:
        verify_input_digest_manifest(manifest, contract_path=contract_path)
    except ValueError as error:
        raise FreezeInputError(str(error)) from error
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--slo-contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--b01-profile", type=Path, required=True)
    parser.add_argument("--baseline-candidate", type=Path, required=True)
    parser.add_argument("--d005-rate-file", type=Path, required=True)
    parser.add_argument("--spike-run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Print the manifest without writing it")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest(
        run_id=args.run_id,
        source_sha=args.source_sha,
        contract_path=args.slo_contract.resolve(),
        b01_profile=args.b01_profile.resolve(),
        baseline_candidate=args.baseline_candidate.resolve(),
        d005_rate_file=args.d005_rate_file.resolve(),
        spike_run_dir=args.spike_run_dir.resolve(),
    )
    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FreezeInputError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"[freeze-input] ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
