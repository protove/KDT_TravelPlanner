#!/usr/bin/env python3
"""Validate an AWS k6 load-test profile against the contract in
aws-load-test-handoff/plans/01_AWS_K6_WORKLOAD_PLAN.md.

This mirrors (in Python, so it can run without a k6 binary) the same checks
load-tests/k6/aws/config.js performs at k6 init time. Plan 03's future
orchestration script is expected to call validate() before starting a run;
load-tests/tests/test_aws_load_profile.py exercises it directly.
"""
import json
import re
from pathlib import Path

DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}$")
PLACEHOLDER_PATTERN = re.compile(r"REPLACE_")

REQUIRED_TOP_LEVEL_FIELDS = (
    "profileVersion",
    "scenarioId",
    "environment",
    "region",
    "sloVersion",
    "seedVersion",
    "requestMixVersion",
    "target",
    "googleApi",
    "k6Image",
    "limits",
    "scenarios",
    "requestMix",
)

REQUIRED_SCENARIOS = ("smoke", "ramp", "baseline", "spike")
CAPACITY_STRESS_PROFILE_VERSIONS = {
    "aws-ec2-eks-capacity-stress-v1.0",
    "aws-ec2-eks-capacity-stress-v1.1",
}
EKS_BREAKPOINT_PROFILE_VERSION = "aws-eks-monolith-breakpoint-v1.0"


def load_profile(path):
    """Load and JSON-parse a profile file. Raises ValueError on bad JSON."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"profile file is not valid JSON: {path}") from error


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(profile):
    """Validate a parsed profile dict. Raises ValueError on the first
    violation found. Does not require BASE_URL/K6_IMAGE_DIGEST overrides to
    be resolved (that only happens at k6 runtime); this checks the profile
    file's own internal consistency.
    """
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        _require(field in profile, f"profile is missing required field: {field}")

    target = profile["target"]
    _require(isinstance(target, dict) and target.get("baseUrl"), "target.baseUrl is missing")
    base_url = target["baseUrl"]
    if not PLACEHOLDER_PATTERN.search(base_url):
        _require(base_url.startswith("https://"), f"target.baseUrl must be HTTPS: {base_url}")

    google_api = profile["googleApi"]
    _require(
        isinstance(google_api, dict) and google_api.get("enabled") is False,
        "googleApi.enabled must be false",
    )

    k6_image = profile["k6Image"]
    if not PLACEHOLDER_PATTERN.search(k6_image):
        _require(
            DIGEST_PATTERN.search(k6_image) is not None,
            f"k6Image must be pinned by digest (…@sha256:<64 hex>): {k6_image}",
        )

    limits = profile["limits"]
    max_rate = limits.get("maxRate")
    max_vus = limits.get("maxVUs")
    _require(isinstance(max_rate, (int, float)) and max_rate > 0, "limits.maxRate must be a positive number")
    _require(isinstance(max_vus, (int, float)) and max_vus > 0, "limits.maxVUs must be a positive number")

    scenarios = profile["scenarios"]
    for name in REQUIRED_SCENARIOS:
        _require(name in scenarios, f"scenarios.{name} is missing")

    _validate_smoke(scenarios["smoke"])
    _validate_ramp(scenarios["ramp"], max_rate, max_vus)
    _validate_baseline(scenarios["baseline"], max_vus)
    _validate_spike(scenarios["spike"], max_vus)

    request_mix = profile["requestMix"]
    _require("baseline" in request_mix, "requestMix.baseline is missing")
    _validate_mix_sums_to_100(request_mix["baseline"], "requestMix.baseline")
    if "spike" in request_mix:
        _validate_mix_sums_to_100(request_mix["spike"], "requestMix.spike")
    if profile.get("profileVersion") == "aws-ec2-eks-comparison-v1.1":
        _require(profile.get("sloVersion") in {"v1.1-candidate", "v1.1-frozen"}, "comparison profile must use the v1.1 contract")
        for name in ("soak", "scale-step"):
            _require(name in scenarios, f"scenarios.{name} is missing")
            _require(scenarios[name].get("maxVUs", 0) <= max_vus, f"scenarios.{name}.maxVUs exceeds limits.maxVUs")
        _require("normal" in request_mix, "requestMix.normal is missing")
        _validate_mix_sums_to_100(request_mix["normal"], "requestMix.normal")
        _require("soak" in request_mix, "requestMix.soak is missing")
        _validate_mix_sums_to_100(request_mix["soak"], "requestMix.soak")
    if profile.get("profileVersion") in CAPACITY_STRESS_PROFILE_VERSIONS:
        _validate_capacity_stress(profile)
    if profile.get("profileVersion") == EKS_BREAKPOINT_PROFILE_VERSION:
        _validate_eks_breakpoint(profile)

    return True


def _validate_smoke(smoke):
    _require(smoke.get("vus", 0) > 0, "scenarios.smoke.vus must be a positive number")
    _require(smoke.get("iterations", 0) > 0, "scenarios.smoke.iterations must be a positive number")


def _validate_ramp(ramp, max_rate, max_vus):
    stages = ramp.get("stages")
    _require(isinstance(stages, list) and len(stages) > 0, "scenarios.ramp.stages must be a non-empty array")
    for stage in stages:
        rate = stage.get("targetRate")
        _require(isinstance(rate, (int, float)) and rate > 0, "each ramp stage needs a positive targetRate")
        _require(rate <= max_rate, f"ramp stage targetRate {rate} exceeds limits.maxRate {max_rate}")
        _require(stage.get("duration"), "each ramp stage needs a duration")
    _require(
        ramp.get("preAllocatedVUs", 0) <= max_vus,
        "scenarios.ramp.preAllocatedVUs exceeds limits.maxVUs",
    )
    _require(ramp.get("maxVUs", 0) <= max_vus, "scenarios.ramp.maxVUs exceeds limits.maxVUs")


def _validate_baseline(baseline, max_vus):
    rate = baseline.get("rate")
    _require(
        rate is None or (isinstance(rate, (int, float)) and rate > 0),
        "scenarios.baseline.rate must be null (unset, pending D-005) or a positive number",
    )
    _require(baseline.get("duration"), "scenarios.baseline.duration is missing")
    _require(baseline.get("warmup"), "scenarios.baseline.warmup is missing")
    _require(baseline.get("maxVUs", 0) <= max_vus, "scenarios.baseline.maxVUs exceeds limits.maxVUs")


def _validate_spike(spike, max_vus):
    _require(
        spike.get("peakRateMultiplier", 0) > 1,
        "scenarios.spike.peakRateMultiplier must be greater than 1",
    )
    _require(spike.get("hold"), "scenarios.spike.hold is missing")
    _require(spike.get("maxVUs", 0) <= max_vus, "scenarios.spike.maxVUs exceeds limits.maxVUs")


def _validate_mix_sums_to_100(mix, label):
    total = sum(mix.values())
    _require(round(total) == 100, f"{label} weights must sum to 100, got {total}")


def _validate_capacity_stress(profile):
    """Validate the separate post-freeze Capacity/Scale Stress contract.

    The base rate is intentionally resolved at execution time from the frozen
    Baseline contract. This validator checks deterministic stage multipliers
    and safety ceilings, but never invents or freezes a normal rate.
    """
    _require(profile.get("sloVersion") == "v1.1-frozen", "capacity stress must consume v1.1-frozen")
    _require(
        profile.get("requestMixVersion") == "aws-ec2-eks-comparison-v1.1",
        "capacity stress must use the comparison request mix",
    )
    limits = profile.get("limits", {})
    max_vus = limits.get("maxVUs")
    _require(
        isinstance(max_vus, (int, float)) and max_vus >= 300,
        "capacity stress limits.maxVUs must be at least 300",
    )
    stress = profile.get("capacityStress")
    _require(isinstance(stress, dict), "capacityStress is missing")
    multipliers = stress.get("stageMultipliers")
    durations = stress.get("stageDurations")
    _require(multipliers == [1, 2, 4, 8], "capacityStress.stageMultipliers must be [1, 2, 4, 8]")
    _require(
        isinstance(durations, list) and len(durations) == len(multipliers),
        "capacityStress.stageDurations must match stageMultipliers",
    )
    for duration in durations:
        _require(
            isinstance(duration, str) and re.fullmatch(r"[1-9][0-9]*[smh]", duration),
            f"invalid capacity stress duration: {duration}",
        )
    for name in (
        "stageGraceSeconds",
        "capacityStabilitySeconds",
        "scaleInObservationSeconds",
        "hardTimeCeilingSeconds",
        "preAllocatedVUs",
        "maxVUs",
        "seededUsers",
        "runnerRepairLimit",
    ):
        value = stress.get(name)
        _require(isinstance(value, int) and value > 0, f"capacityStress.{name} must be a positive integer")
    _require(stress["maxVUs"] == max_vus, "capacityStress.maxVUs must equal limits.maxVUs")
    _require(stress["preAllocatedVUs"] <= stress["maxVUs"], "capacityStress.preAllocatedVUs exceeds maxVUs")
    _require(stress["seededUsers"] >= stress["maxVUs"], "capacityStress.seededUsers must cover maxVUs")
    _require(stress["runnerRepairLimit"] == 1, "capacityStress.runnerRepairLimit must be exactly one")
    scenario = profile.get("scenarios", {}).get("capacity-stress")
    _require(isinstance(scenario, dict), "scenarios.capacity-stress is missing")
    _require(
        scenario.get("stageMultipliers") == multipliers,
        "scenarios.capacity-stress multipliers do not match capacityStress",
    )
    _require(
        scenario.get("stageDurations") == durations,
        "scenarios.capacity-stress durations do not match capacityStress",
    )
    _require(
        scenario.get("maxVUs") == stress["maxVUs"],
        "scenarios.capacity-stress.maxVUs does not match capacityStress",
    )
    _require(
        scenario.get("preAllocatedVUs") == stress["preAllocatedVUs"],
        "scenarios.capacity-stress.preAllocatedVUs does not match capacityStress",
    )
    _require("normal" in profile.get("requestMix", {}), "requestMix.normal is missing for capacity stress")
    _validate_mix_sums_to_100(profile["requestMix"]["normal"], "requestMix.normal")


def _validate_eks_breakpoint(profile):
    """Validate the EKS-only breakpoint contract without changing the base
    2/2/4 node group or 2-4 HPA.  The final stage is a bounded observation
    ceiling; it is not a claim that the platform's maximum capacity was found.
    """
    target = profile.get("target") or {}
    _require(target.get("platform") == "eks", "EKS breakpoint target.platform must be eks")
    eks = profile.get("eks")
    _require(isinstance(eks, dict), "eks settings are missing")
    _require(eks.get("instanceType") == "t3.small", "EKS breakpoint must use t3.small nodes")
    _require(eks.get("nodeGroup") == {"min": 2, "desired": 2, "max": 4}, "EKS node group must remain 2/2/4")
    _require(eks.get("baseHpa") == {"minReplicas": 2, "maxReplicas": 4}, "base HPA must remain 2-4")
    stress = profile.get("capacityStress")
    _require(isinstance(stress, dict), "capacityStress is missing")
    multipliers = stress.get("stageMultipliers")
    durations = stress.get("stageDurations")
    _require(
        isinstance(multipliers, list) and len(multipliers) >= 5 and multipliers[0] == 1,
        "EKS breakpoint needs at least five stages starting at 1x",
    )
    _require(
        all(isinstance(value, int) and value > 0 for value in multipliers),
        "EKS breakpoint stage multipliers must be positive integers",
    )
    _require(
        all(current == previous * 2 for previous, current in zip(multipliers, multipliers[1:])),
        "EKS breakpoint stage multipliers must double monotonically",
    )
    _require(isinstance(durations, list) and len(durations) == len(multipliers), "EKS breakpoint durations must match multipliers")
    for duration in durations:
        _require(
            isinstance(duration, str) and re.fullmatch(r"[1-9][0-9]*[smh]", duration),
            f"invalid EKS breakpoint duration: {duration}",
        )
    for name in (
        "stageGraceSeconds",
        "capacityStabilitySeconds",
        "hardTimeCeilingSeconds",
        "preAllocatedVUs",
        "maxVUs",
        "seededUsers",
        "runnerRepairLimit",
    ):
        value = stress.get(name)
        _require(isinstance(value, int) and value > 0, f"capacityStress.{name} must be a positive integer")
    _require(stress["maxVUs"] == profile["limits"]["maxVUs"], "EKS breakpoint maxVUs must equal limits.maxVUs")
    _require(stress["preAllocatedVUs"] <= stress["maxVUs"], "EKS breakpoint preAllocatedVUs exceeds maxVUs")
    _require(stress["seededUsers"] >= stress["maxVUs"], "EKS breakpoint seededUsers must cover maxVUs")
    _require(stress["runnerRepairLimit"] == 1, "capacityStress.runnerRepairLimit must be exactly one")
    _require(stress.get("requiresCompleteSloWindows") is True, "EKS breakpoint must require complete SLO windows")
    scenario = profile.get("scenarios", {}).get("capacity-stress")
    _require(isinstance(scenario, dict), "scenarios.capacity-stress is missing")
    _require(scenario.get("stageMultipliers") == multipliers, "EKS breakpoint scenario multipliers do not match capacityStress")
    _require(scenario.get("stageDurations") == durations, "EKS breakpoint scenario durations do not match capacityStress")
    _require(scenario.get("maxVUs") == stress["maxVUs"], "EKS breakpoint scenario maxVUs does not match capacityStress")
    _require(scenario.get("preAllocatedVUs") == stress["preAllocatedVUs"], "EKS breakpoint scenario preAllocatedVUs does not match capacityStress")
    _require("normal" in profile.get("requestMix", {}), "requestMix.normal is missing for EKS breakpoint")
    _validate_mix_sums_to_100(profile["requestMix"]["normal"], "requestMix.normal")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile_path")
    args = parser.parse_args()
    validate(load_profile(args.profile_path))
    print(f"OK: {args.profile_path} is a valid AWS load-test profile")
