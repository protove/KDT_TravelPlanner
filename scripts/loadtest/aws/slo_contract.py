"""Load and evaluate the versioned AWS load-test SLO contract.

The JSON contract is the single source for comparator direction and frozen
recovery window values.  Python consumers import this module; k6 consumes the
same JSON file through ``open`` in ``load-tests/k6/aws/config.js``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPOSITORY_ROOT / "load-tests/aws/contracts/slo-v1.0.json"
CONTRACT_SCHEMA_VERSION = "aws-slo-contract-v1"
FREEZE_MANIFEST_SCHEMA = "aws-d006-freeze-input-manifest-v1"


class SloContractError(ValueError):
    """The versioned contract is missing or structurally invalid."""


def canonical_json(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for input-digest calculation."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SloContractError(message)


def load_contract(path: Path | None = None, *, expected_version: str | None = None) -> dict[str, Any]:
    """Load and validate a supported frozen or comparison candidate contract.

    The default remains the historical v1.0 contract so existing recovery and
    Compose consumers are byte-for-byte compatible.  Comparison runs pass an
    explicit v1.1 candidate/frozen path at action time.
    """

    contract_path = (path or CONTRACT_PATH).resolve()
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SloContractError(f"SLO contract does not exist: {contract_path}") from error
    except json.JSONDecodeError as error:
        raise SloContractError(f"SLO contract is not valid JSON: {contract_path}") from error
    if not isinstance(payload, dict):
        raise SloContractError("SLO contract must be a JSON object")

    contract_version = payload.get("contractVersion")
    slo_version = payload.get("sloVersion")
    _require(
        (contract_version, slo_version) in {
            ("v1.0", "v1.0-frozen"),
            ("v1.1", "v1.1-candidate"),
            ("v1.1", "v1.1-frozen"),
            ("v2.0", "v2.0-breakpoint"),
            ("v2.1", "v2.1-breakpoint"),
        },
        "SLO contract must be v1.0-frozen, v1.1 candidate/frozen or v2.0-breakpoint",
    )
    if expected_version is not None:
        _require(slo_version == expected_version, f"SLO sloVersion must be {expected_version}")
    comparators = payload.get("comparators")
    _require(isinstance(comparators, dict), "SLO comparators must be an object")
    for name in (
        "p95Ms",
        "successRate",
        "unexpectedErrorRate",
        "baselineContractFailureRate",
        "recoveryContractFailureRate",
        "droppedIterations",
        "runnerBottleneckSuspected",
        "capacityFloorRatio",
        "recoveryBudgetSeconds",
        "r01UnexpectedErrorCount",
        "r01ContractFailureCount",
    ):
        item = comparators.get(name)
        _require(isinstance(item, dict), f"SLO comparator is missing: {name}")
        _require(item.get("operator") in {"<", "<=", "==", ">=", ">"}, f"invalid comparator operator: {name}")
        _require("value" in item, f"comparator value is missing: {name}")

    baseline = payload.get("baseline")
    recovery = payload.get("recovery")
    _require(isinstance(baseline, dict), "SLO baseline section is missing")
    _require(isinstance(recovery, dict), "SLO recovery section is missing")
    expected_repetitions = 1 if contract_version in {"v2.0", "v2.1"} else 3
    _require(baseline.get("repetitions") == expected_repetitions, f"SLO baseline repetitions must be {expected_repetitions}")
    _require(baseline.get("warmupExcluded") is True, "SLO baseline warmupExcluded must be true")
    _require(recovery.get("bucketSeconds") == 10, "SLO recovery bucketSeconds must be 10")
    _require(recovery.get("stableWindowSeconds") == 120, "SLO recovery stableWindowSeconds must be 120")
    _require(recovery.get("budgetSeconds") == 600, "SLO recovery budgetSeconds must be 600")
    _require(baseline.get("p95Ms") == comparators["p95Ms"]["value"], "baseline p95Ms disagrees with comparator")
    _require(baseline.get("successRate") == comparators["successRate"]["value"], "baseline successRate disagrees with comparator")
    _require(baseline.get("unexpectedErrorRate") == comparators["unexpectedErrorRate"]["value"], "baseline unexpectedErrorRate disagrees with comparator")
    _require(baseline.get("contractFailureRate") == comparators["baselineContractFailureRate"]["value"], "baseline contractFailureRate disagrees with comparator")
    _require(baseline.get("droppedIterations") == comparators["droppedIterations"]["value"], "baseline droppedIterations disagrees with comparator")
    _require(recovery.get("p95Ms") == comparators["p95Ms"]["value"], "recovery p95Ms disagrees with comparator")
    _require(recovery.get("capacityFloorRatio") == comparators["capacityFloorRatio"]["value"], "recovery capacityFloorRatio disagrees with comparator")
    _require(recovery.get("unexpectedErrorRate") == comparators["unexpectedErrorRate"]["value"], "recovery unexpectedErrorRate disagrees with comparator")
    _require(recovery.get("contractFailureRate") == comparators["recoveryContractFailureRate"]["value"], "recovery contractFailureRate disagrees with comparator")
    _require(recovery.get("budgetSeconds") == comparators["recoveryBudgetSeconds"]["value"], "recovery budgetSeconds disagrees with comparator")
    _require(payload.get("spike", {}).get("classification") == "diagnostic", "Spike must be diagnostic")
    _require(payload.get("spike", {}).get("sloPassRequired") is False, "Spike cannot be an SLO pass gate")
    _require(payload.get("r01", {}).get("unexpectedErrorCount") == 0, "R-01 unexpected error count must be zero")
    _require(payload.get("r01", {}).get("contractFailureCount") == 0, "R-01 contract failure count must be zero")
    if contract_version in {"v1.1", "v2.0", "v2.1"}:
        comparison = payload.get("comparison")
        _require(isinstance(comparison, dict), f"{contract_version} comparison section is missing")
        _require(comparison.get("platforms") == ["ec2-asg", "eks"], f"{contract_version} comparison platforms must be EC2 ASG and EKS")
        expected_instance_family = "t3.medium" if contract_version == "v2.1" else ("t3.small" if contract_version == "v2.0" or slo_version == "v1.1-candidate" else "t3.medium")
        _require(
            comparison.get("sameInstanceFamily") == expected_instance_family,
            f"{slo_version} comparison instance family must be {expected_instance_family}",
        )
        capacity_shape = comparison.get("sameCapacityShape")
        _require(capacity_shape == {"min": 2, "desired": 2, "max": 4}, f"{contract_version} comparison capacity shape must be 2/2/4")
    return payload


def comparator(contract: dict[str, Any], name: str) -> tuple[str, Any]:
    item = contract["comparators"].get(name)
    if not isinstance(item, dict):
        raise SloContractError(f"unknown SLO comparator: {name}")
    return str(item["operator"]), item["value"]


def compare(actual: Any, operator: str, expected: Any) -> bool:
    """Apply one explicit comparator; bool is not accepted as numeric data."""

    if isinstance(expected, bool):
        return actual is expected if operator == "==" else False
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    if not math.isfinite(float(actual)):
        return False
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    if operator == "==":
        return actual == expected
    if operator == ">=":
        return actual >= expected
    if operator == ">":
        return actual > expected
    raise SloContractError(f"unsupported comparator operator: {operator}")


def satisfies(contract: dict[str, Any], name: str, actual: Any) -> bool:
    operator, expected = comparator(contract, name)
    return compare(actual, operator, expected)


def threshold_expression(contract: dict[str, Any], name: str, metric: str) -> str:
    """Build a k6 threshold expression using the contract comparator."""

    operator, expected = comparator(contract, name)
    return f"{metric}{operator}{expected}"


def verify_input_digest_manifest(manifest: dict[str, Any], *, contract_path: Path | None = None) -> bool:
    """Verify the non-circular digest portion of a D-006 input manifest."""

    if manifest.get("schemaVersion") != FREEZE_MANIFEST_SCHEMA:
        raise SloContractError("freeze input manifest schemaVersion is invalid")
    if manifest.get("sloVersion") != "v1.0-frozen":
        raise SloContractError("freeze input manifest sloVersion is invalid")
    if not isinstance(manifest.get("runId"), str) or not manifest["runId"].strip():
        raise SloContractError("freeze input manifest runId is missing")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise SloContractError("freeze input manifest inputs are missing")
    if manifest.get("inputDigest") != digest_json(inputs):
        raise SloContractError("freeze input manifest inputDigest does not match inputs")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise SloContractError("freeze input manifest contract metadata is missing")
    contract_digest = contract.get("sha256")
    if not isinstance(contract_digest, str) or not SHA256_RE.fullmatch(contract_digest):
        raise SloContractError("freeze input manifest contract.sha256 is invalid")
    if contract_path is not None and sha256_file(contract_path) != contract_digest:
        raise SloContractError("freeze input manifest contract digest does not match the contract file")

    # The effective Spike configuration is outside ``inputs`` to keep the
    # manifest readable, but its digest is one of the immutable input fields.
    # Bind both copies so a post-build edit to the effective config cannot be
    # accepted while leaving ``inputDigest`` unchanged.
    spike = manifest.get("spike")
    if not isinstance(spike, dict) or spike.get("classification") != "diagnostic":
        raise SloContractError("freeze input manifest spike section must be diagnostic")
    effective = spike.get("effectiveConfig")
    if not isinstance(effective, dict):
        raise SloContractError("freeze input manifest spike effectiveConfig is missing")
    effective_digest = spike.get("effectiveConfigSha256")
    if not isinstance(effective_digest, str) or not SHA256_RE.fullmatch(effective_digest):
        raise SloContractError("freeze input manifest spike effectiveConfigSha256 is invalid")
    if effective_digest != digest_json(effective):
        raise SloContractError("freeze input manifest spike effectiveConfig digest does not match effectiveConfig")
    if inputs.get("spikeEffectiveConfigSha256") != effective_digest:
        raise SloContractError("freeze input manifest input spike digest does not match effectiveConfig")
    if effective.get("scenario") != "spike" or effective.get("classification") != "diagnostic":
        raise SloContractError("freeze input manifest spike effectiveConfig classification is invalid")
    if effective.get("profileSha256") != inputs.get("b01ProfileSha256"):
        raise SloContractError("freeze input manifest spike profile does not match B-01 profile")
    try:
        baseline_rate = float(effective.get("baselineRate"))
        peak_rate = float(effective.get("peakRate"))
        multiplier = float(effective.get("peakRateMultiplier"))
        frozen_rate = float(inputs.get("d005ArrivalRate"))
    except (TypeError, ValueError) as error:
        raise SloContractError("freeze input manifest spike rates are invalid") from error
    if not all(math.isfinite(value) and value > 0 for value in (baseline_rate, peak_rate, multiplier)):
        raise SloContractError("freeze input manifest spike rates must be finite and positive")
    if not math.isclose(baseline_rate, frozen_rate, rel_tol=0, abs_tol=1e-9):
        raise SloContractError("freeze input manifest spike baselineRate does not match D-005 rate")
    if multiplier <= 1 or not math.isclose(peak_rate, baseline_rate * multiplier, rel_tol=0, abs_tol=1e-9):
        raise SloContractError("freeze input manifest spike peak rate relationship is invalid")
    return True


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
