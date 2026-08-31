#!/usr/bin/env python3
"""Validate the AWS Recovery profile without contacting AWS.

The B-01 profile validator intentionally knows about B-01's four phases. A
Recovery run has a separate contract, so this validator stays independent and
prevents a Recovery caller from silently falling back to the B-01 profile.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from slo_contract import load_contract
except ImportError:  # pragma: no cover - supports direct import by external callers
    from scripts.loadtest.aws.slo_contract import load_contract


DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}$")
PLACEHOLDER_PATTERN = re.compile(r"REPLACE_")
DEFAULT_SLO_CONTRACT = load_contract()
REQUIRED = (
    "profileVersion",
    "scenarioId",
    "platform",
    "environment",
    "region",
    "sloVersion",
    "seedVersion",
    "requestMixVersion",
    "target",
    "backend",
    "runner",
    "googleApi",
    "k6Image",
    "limits",
    "recovery",
    "requestMix",
    "observability",
)
REQUIRED_RECOVERY = (
    "executor",
    "timeUnit",
    "warmup",
    "duration",
    "preAllocatedVUs",
    "maxVUs",
    "bucketSeconds",
    "stableWindowSeconds",
    "budgetSeconds",
    "p95Ms",
    "capacityFloorRatio",
    "unexpectedErrorRate",
    "contractFailureRate",
)


def load_profile(path: Path) -> dict:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"profile file does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"profile file is not valid JSON: {path}") from error
    if not isinstance(profile, dict):
        raise ValueError("profile must be a JSON object")
    return profile


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(profile: dict) -> bool:
    for field in REQUIRED:
        require(field in profile, f"profile is missing required field: {field}")
    require(profile["scenarioId"] in {"AWS-RECOVERY", "AWS-RECOVERY-COMPARISON"}, "scenarioId must be an approved Recovery scenario")
    require(profile["platform"] in {"ec2", "eks", "comparison"}, "platform must be ec2, eks or comparison")
    contract_path = Path(__file__).resolve().parents[3] / "load-tests/aws/contracts/slo-v1.0.json"
    if profile["sloVersion"] in {"v1.1-candidate", "v1.1-frozen"}:
        contract_path = contract_path.with_name(f"slo-{profile['sloVersion']}.json")
    slo_contract = load_contract(contract_path, expected_version=profile["sloVersion"])
    require(isinstance(profile["environment"], str) and profile["environment"], "environment is required")
    require(re.fullmatch(r"[a-z0-9-]+", profile["region"]) is not None, "region is invalid")

    target = profile["target"]
    require(isinstance(target, dict) and isinstance(target.get("baseUrl"), str), "target.baseUrl is required")
    if not PLACEHOLDER_PATTERN.search(target["baseUrl"]):
        require(target["baseUrl"].startswith("https://"), "target.baseUrl must be HTTPS")
    expected_tags = target.get("expectedTags")
    require(isinstance(expected_tags, dict) and expected_tags.get("Environment"), "target.expectedTags.Environment is required")

    for resource in ("backend", "runner"):
        tags = profile[resource].get("expectedTags")
        require(isinstance(tags, dict) and tags.get("Environment"), f"{resource}.expectedTags.Environment is required")
    require(profile["backend"]["expectedTags"].get("Service"), "backend.expectedTags.Service is required")
    require(profile["runner"]["expectedTags"].get("Service"), "runner.expectedTags.Service is required")

    require(profile["googleApi"].get("enabled") is False, "googleApi.enabled must be false")
    image = profile["k6Image"]
    require(isinstance(image, str) and image, "k6Image is required")
    if not PLACEHOLDER_PATTERN.search(image):
        require(DIGEST_PATTERN.search(image) is not None, "k6Image must be digest-pinned")

    limits = profile["limits"]
    require(isinstance(limits.get("maxRate"), (int, float)) and limits["maxRate"] > 0, "limits.maxRate must be positive")
    require(isinstance(limits.get("maxVUs"), (int, float)) and limits["maxVUs"] > 0, "limits.maxVUs must be positive")

    recovery = profile["recovery"]
    for field in REQUIRED_RECOVERY:
        require(field in recovery, f"recovery.{field} is missing")
    require(recovery["executor"] == "constant-arrival-rate", "recovery.executor must be constant-arrival-rate")
    require(recovery["rate"] is None or (isinstance(recovery["rate"], (int, float)) and recovery["rate"] > 0), "recovery.rate must be null or positive")
    contract_recovery = slo_contract["recovery"]
    require(recovery["bucketSeconds"] == contract_recovery["bucketSeconds"], "recovery.bucketSeconds does not match SLO contract")
    require(recovery["stableWindowSeconds"] == contract_recovery["stableWindowSeconds"], "recovery.stableWindowSeconds does not match SLO contract")
    require(recovery["budgetSeconds"] == contract_recovery["budgetSeconds"], "recovery.budgetSeconds does not match SLO contract")
    require(recovery["p95Ms"] == contract_recovery["p95Ms"], "recovery.p95Ms does not match SLO contract")
    require(recovery["capacityFloorRatio"] == contract_recovery["capacityFloorRatio"], "recovery.capacityFloorRatio does not match SLO contract")
    require(recovery["unexpectedErrorRate"] == contract_recovery["unexpectedErrorRate"], "recovery.unexpectedErrorRate does not match SLO contract")
    require(recovery["contractFailureRate"] == contract_recovery["contractFailureRate"], "recovery.contractFailureRate does not match SLO contract")
    require(0 < recovery["capacityFloorRatio"] <= 1, "recovery.capacityFloorRatio must be in (0,1]")
    require(0 <= recovery["unexpectedErrorRate"] < 1, "recovery.unexpectedErrorRate must be in [0,1)")
    require(recovery["contractFailureRate"] == 0, "recovery.contractFailureRate must be zero")
    require(recovery["maxVUs"] <= limits["maxVUs"], "recovery.maxVUs exceeds limits.maxVUs")
    require(recovery["preAllocatedVUs"] <= recovery["maxVUs"], "recovery.preAllocatedVUs exceeds recovery.maxVUs")

    steady_mix = profile["requestMix"].get("steady")
    require(isinstance(steady_mix, dict) and steady_mix, "requestMix.steady is required")
    require(round(sum(steady_mix.values())) == 100, "requestMix.steady weights must sum to 100")
    require(set(steady_mix) == {"refresh", "travelList", "travelDetail", "mapPoints", "timelineCreate", "orderChange"}, "requestMix.steady keys are not the approved set")

    required_metrics = profile["observability"].get("required")
    require(isinstance(required_metrics, list) and required_metrics, "observability.required is required")
    require(all(isinstance(metric, str) and metric for metric in required_metrics), "observability.required entries must be non-empty strings")
    require(profile["observability"].get("statusPath"), "observability.statusPath is required")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    validate(load_profile(args.profile))
    print(f"OK: {args.profile} is a valid AWS Recovery profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
