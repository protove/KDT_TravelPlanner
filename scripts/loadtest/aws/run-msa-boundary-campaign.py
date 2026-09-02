#!/usr/bin/env python3
"""Build and validate the SCRUM-80 EKS monolith MSA-boundary campaign.

The script is deliberately a small, deterministic planner.  It never calls
AWS or changes Kubernetes state; the existing reviewed stage runner remains
the only live mutation path.  A live operator can use the emitted stage list
to invoke that runner and then feed sealed balanced-stage metrics to
``analyze-msa-boundary-campaign.py`` before starting the two hotspot stages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED_OPERATIONS = {
    "refresh", "profileRead", "travelList", "travelDetail", "travelUpdate",
    "countryList", "cityList", "placeSearch", "nearbySearch", "mapPoints",
    "routeGet", "routePreview", "timelineCreate", "orderChange", "memberList",
    "invitationList", "communityCategoryList", "communityPostList",
    "communityPostDetail", "communityCommentList", "communityMyPosts",
    "communityMyComments", "communityPostUpdate", "communityCommentUpdate",
    "communityPostReaction", "communityCommentReaction",
}


class CampaignError(ValueError):
    """A sanitized campaign contract error."""


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CampaignError(f"invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise CampaignError(f"JSON object expected: {path}")
    return payload


def validate_operation_map(profile: dict, operation_map: dict) -> list[dict]:
    operations = operation_map.get("operations")
    if not isinstance(operations, list) or len(operations) != 26:
        raise CampaignError("operation map must contain exactly 26 operations")
    ids = [item.get("id") for item in operations if isinstance(item, dict)]
    if set(ids) != EXPECTED_OPERATIONS or len(ids) != len(set(ids)):
        raise CampaignError("operation map does not contain the exact current-feature operation set")
    if operation_map.get("weightTotal") != 100 or sum(float(item.get("weight", 0)) for item in operations) != 100:
        raise CampaignError("operation map weights must sum to 100")
    endpoints = [(item.get("method"), item.get("route")) for item in operations]
    if any(not method or not route for method, route in endpoints) or len(endpoints) != len(set(endpoints)):
        raise CampaignError("operation map contains an empty or duplicate method/route")
    normal = profile.get("requestMix", {}).get("normal")
    if not isinstance(normal, dict) or set(normal) != EXPECTED_OPERATIONS:
        raise CampaignError("profile requestMix.normal does not match the operation map")
    for item in operations:
        if float(normal[item["id"]]) != float(item["weight"]):
            raise CampaignError(f"operation weight mismatch: {item['id']}")
    return operations


def validate_profile(profile: dict) -> dict:
    if profile.get("profileVersion") != "aws-eks-monolith-msa-boundary-v1.0":
        raise CampaignError("unexpected MSA boundary profile version")
    stress = profile.get("capacityStress") or {}
    if stress.get("balancedRates") != [64, 128, 192, 224, 256]:
        raise CampaignError("balanced rates must be 64,128,192,224,256")
    if stress.get("fixedRpsCeiling") is not None:
        raise CampaignError("fixedRpsCeiling must remain null")
    if stress.get("hotspotSharePercent") != 60:
        raise CampaignError("hotspot share must be 60 percent")
    if stress.get("spikeRate") != 256 or stress.get("recoveryRate") != 16:
        raise CampaignError("spike/recovery rates are invalid")
    if (profile.get("eks") or {}).get("nodeGroup") != {"min": 2, "desired": 2, "max": 4}:
        raise CampaignError("EKS node group must remain 2/2/4")
    if (profile.get("eks") or {}).get("baseHpa") != {"minReplicas": 2, "maxReplicas": 4}:
        raise CampaignError("base HPA must remain 2-4")
    return stress


def build_campaign_plan(profile: dict, operations: list[dict], candidates: list[str] | None = None) -> dict:
    stress = validate_profile(profile)
    if isinstance(operations, dict):
        operations = validate_operation_map(profile, operations)
    if not isinstance(operations, list):
        raise CampaignError("operation map operations must be an array")
    candidate_order = stress.get("hotspotCandidateOrder") or []
    selected = list(candidates or candidate_order[:2])
    if len(selected) != 2 or len(set(selected)) != 2:
        raise CampaignError("exactly two distinct hotspot candidates are required")
    known_dimensions = {
        value
        for item in operations
        for value in (item.get("id"), item.get("service"), item.get("domain"), item.get("subdomain"))
    }
    if any(candidate not in known_dimensions for candidate in selected):
        raise CampaignError("hotspot candidate is not present in the operation map")
    stages = [
        {"id": "smoke", "kind": "functional", "rate": None, "allOperations": True},
        {"id": "baseline-16", "kind": "baseline", "rate": 16, "holdSeconds": 180},
    ]
    stages.extend(
        {"id": f"balanced-{rate}", "kind": "balanced", "rate": rate, "holdSeconds": stress["nominalHoldSeconds"], "extensionSeconds": stress["conditionalExtensionSeconds"]}
        for rate in stress["balancedRates"]
    )
    stages.extend(
        {"id": f"hotspot-{index}", "kind": "hotspot", "candidate": candidate, "rate": stress["balancedRates"][-1], "sharePercent": stress["hotspotSharePercent"], "holdSeconds": stress["hotspotHoldSeconds"]}
        for index, candidate in enumerate(selected, start=1)
    )
    stages.extend([
        {"id": "spike-256", "kind": "immediate-spike", "rate": stress["spikeRate"], "startState": "canonical-2-pod-2-node"},
        {"id": "recovery-16", "kind": "recovery", "rate": stress["recoveryRate"], "totalObservationSeconds": stress["recoveryObservationSeconds"], "healthyStabilitySeconds": stress["recoveryHealthyStabilitySeconds"], "restore": ["hpa-2-4", "mock-normal"], "observeScaleIn": True},
    ])
    return {
        "schemaVersion": "scrum80-msa-boundary-campaign/v1",
        "profileVersion": profile["profileVersion"],
        "operationMapVersion": "aws-msa-boundary-operation-map-v1.0",
        "balancedRates": stress["balancedRates"],
        "selectedHotspots": selected,
        "noHiddenRpsCeiling": stress["fixedRpsCeiling"] is None,
        "stages": stages,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--operation-map", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hotspot", action="append", dest="hotspots", default=[])
    parser.add_argument("--dry-run", action="store_true", help="Emit the deterministic stage plan without AWS calls")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        profile = load_json(args.profile)
        operations = validate_operation_map(profile, load_json(args.operation_map))
        plan = build_campaign_plan(profile, operations, args.hotspots or None)
    except CampaignError as error:
        print(f"ERROR: {error}")
        return 2
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
