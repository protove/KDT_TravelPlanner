#!/usr/bin/env python3
"""Fail-closed validation for an approved dev-runtime rollout plan.

The Terraform module enforces the mode/digest contract at plan time.  This
small, dependency-free adapter adds the second boundary that Terraform cannot
express: a saved plan may change only the Backend launch template, Backend ASG
refresh settings, the optional CPU target-tracking policy, and the image
contract marker.  It is intentionally read-only and never calls AWS or
Terraform apply.

For a post-restore drift check, pass ``--refresh-only`` with the sanitized
``restoration_state_contract`` emitted by the module.  A refresh-only plan is
valid only when it has no resource actions and the contract is
``MANUAL_BASELINE``.  The adapter does not mark AWS state as verified; the
evidence exporter must perform the independent AWS read-back and write
``status=verified``/``capacityRestored=true``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


class RolloutPlanError(ValueError):
    """Raised when a rollout plan or contract is unsafe to use."""


_DIGEST_RE = re.compile(
    r"^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/"
    r"[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$"
)
_ALLOWED_MODES = {"NORMAL", "EXPERIMENT", "FAULT", "MANUAL_BASELINE"}
_NOOP = ("no-op",)
_LAUNCH_TEMPLATE_VERSION_RE = re.compile(r"^[1-9][0-9]*$")


def _actions(resource: dict[str, Any]) -> tuple[str, ...]:
    change = resource.get("change")
    if not isinstance(change, dict) or not isinstance(change.get("actions"), list):
        raise RolloutPlanError("resource change is missing actions")
    actions = tuple(str(action) for action in change["actions"])
    if not actions:
        raise RolloutPlanError("resource change has an empty action list")
    return actions


def _allowed_actions(address: str) -> set[tuple[str, ...]] | None:
    if address in {
        "module.backend_service.aws_launch_template.backend",
        "module.backend_service.aws_autoscaling_group.backend",
    }:
        return {_NOOP, ("create",), ("update",)}
    if address == "module.backend_service.aws_autoscaling_policy.cpu[0]":
        # Disabling scaling in an experiment deletes exactly this policy. No
        # replacement (create+delete) is permitted for any rollout resource.
        return {_NOOP, ("create",), ("update",), ("delete",)}
    if address in {
        "terraform_data.backend_image_contract",
        "module.backend_service.terraform_data.backend_image_contract",
    }:
        return {_NOOP, ("create",), ("update",), ("delete",)}
    return None


def validate_plan(plan: dict[str, Any], *, refresh_only: bool = False) -> dict[str, Any]:
    """Validate Terraform JSON plan actions and return sanitized summary."""

    resources = plan.get("resource_changes")
    if not isinstance(resources, list):
        raise RolloutPlanError("Terraform JSON plan has no resource_changes list")

    changed: list[dict[str, Any]] = []
    violations: list[str] = []
    for resource in resources:
        if not isinstance(resource, dict) or not isinstance(resource.get("address"), str):
            violations.append("resource change has no address")
            continue
        address = resource["address"]
        try:
            actions = _actions(resource)
        except RolloutPlanError as exc:
            violations.append(f"{address}: {exc}")
            continue
        if actions != _NOOP:
            changed.append({"address": address, "actions": list(actions)})
        allowed = _allowed_actions(address)
        if allowed is None:
            if actions != _NOOP:
                violations.append(f"forbidden resource action: {address}")
        elif actions not in allowed:
            violations.append(f"forbidden action for {address}: {','.join(actions)}")

    if refresh_only and changed:
        violations.append("refresh-only restore plan must contain no resource actions")
    if violations:
        raise RolloutPlanError("; ".join(violations))
    return {
        "passed": True,
        "refreshOnly": refresh_only,
        "changedResources": changed,
    }


def _value(contract: dict[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    if camel in contract:
        return contract[camel]
    return contract.get(snake, default)


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise RolloutPlanError(f"{field} must be a digest-pinned ECR image URI")
    return value


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RolloutPlanError(f"{field} must be an integer >= {minimum}")
    return value


def validate_contract(contract: dict[str, Any], *, refresh_only: bool = False) -> dict[str, Any]:
    """Validate the sanitized rollout/restoration contract emitted by Terraform."""

    mode = _value(contract, "mode", "rollout_mode")
    if mode not in _ALLOWED_MODES:
        raise RolloutPlanError("contract mode is not an approved rollout mode")
    restoration_shape = "status" in contract and "normalImageDigest" in contract
    if restoration_shape:
        if contract.get("status") != "planned" or contract.get("manualBaselineRequired") is not True:
            raise RolloutPlanError("restoration contract must be a planned MANUAL_BASELINE contract")
        minimum, maximum, checkpoints = 100, 200, []
    else:
        minimum = _require_int(_value(contract, "minHealthyPercentage", "rollout_min_healthy_percentage"), "minHealthyPercentage")
        maximum = _require_int(_value(contract, "maxHealthyPercentage", "rollout_max_healthy_percentage"), "maxHealthyPercentage")
        checkpoints = _value(contract, "checkpointPercentages", "rollout_checkpoint_percentages", [])
        if not isinstance(checkpoints, list) or any(
            isinstance(item, bool) or not isinstance(item, int) for item in checkpoints
        ):
            raise RolloutPlanError("checkpointPercentages must be a list of integers")
    scaling_enabled = _value(contract, "scalingPolicyEnabled", "rollout_scaling_policy_enabled")
    if not isinstance(scaling_enabled, bool):
        raise RolloutPlanError("scalingPolicyEnabled must be boolean")
    auto_rollback = _value(contract, "autoRollback", "auto_rollback")
    if auto_rollback is not False:
        raise RolloutPlanError("rollout contract must disable autoRollback")
    launch_template_version = _value(contract, "launchTemplateVersionRef", "launch_template_version_ref")
    if launch_template_version is None:
        launch_template_version = _value(contract, "launchTemplateVersion", "launch_template_version")
    if not isinstance(launch_template_version, str) or not _LAUNCH_TEMPLATE_VERSION_RE.fullmatch(launch_template_version):
        raise RolloutPlanError("rollout contract requires a numbered Launch Template version")
    desired_capacity = _require_int(_value(contract, "desiredCapacity", "desired_capacity"), "desiredCapacity")
    min_size = _require_int(_value(contract, "minSize", "min_size"), "minSize")
    max_size = _require_int(_value(contract, "maxSize", "max_size"), "maxSize")
    if (desired_capacity, min_size, max_size) != (2, 2, 4):
        raise RolloutPlanError("rollout contract must preserve the 2/2/4 ASG capacity")

    normal = (
        contract.get("normalImageDigest")
        if restoration_shape
        else _value(contract, "normalBackendImageUri", "rollout_normal_backend_image_uri")
    )
    fault = _value(contract, "faultBackendImageUri", "rollout_fault_backend_image_uri")
    restore = (
        normal
        if restoration_shape
        else _value(contract, "restoreBackendImageUri", "rollout_restore_backend_image_uri")
    )
    if normal is not None:
        _require_digest(normal, "normalBackendImageUri")
    if fault is not None:
        _require_digest(fault, "faultBackendImageUri")
    if restore is not None:
        _require_digest(restore, "restoreBackendImageUri")

    if _value(contract, "capacityRestored", "capacity_restored", False) not in {False, None}:
        # Terraform can describe the desired restore contract, but it cannot
        # verify live ASG capacity. Only the AWS read-back exporter may set
        # this field in its separate, sanitized evidence artifact.
        raise RolloutPlanError("Terraform restoration contract cannot claim capacityRestored")

    if mode in {"NORMAL", "MANUAL_BASELINE"}:
        if (minimum, maximum, checkpoints, scaling_enabled) != (100, 200, [], True):
            raise RolloutPlanError("normal/manual rollout must be 100/200, no checkpoints, scaling enabled")
    else:
        if minimum != 100 or maximum != 150 or checkpoints not in ([50], [50, 100]) or scaling_enabled:
            raise RolloutPlanError("experiment/fault rollout must be 100/150, [50]/[50,100], scaling disabled")

    if mode == "MANUAL_BASELINE":
        if not normal or not restore or normal != restore:
            raise RolloutPlanError("MANUAL_BASELINE requires identical normal and restore digests")
    elif mode in {"NORMAL", "EXPERIMENT"} and not normal:
        raise RolloutPlanError("normal/experiment rollout requires a normal digest")
    elif mode == "FAULT":
        if not normal or not fault or normal == fault:
            raise RolloutPlanError("FAULT rollout requires distinct normal and fault digests")

    if refresh_only and mode != "MANUAL_BASELINE":
        raise RolloutPlanError("refresh-only restore validation requires MANUAL_BASELINE")
    return {
        "mode": mode,
        "minHealthyPercentage": minimum,
        "maxHealthyPercentage": maximum,
        "checkpointPercentages": checkpoints,
        "scalingPolicyEnabled": scaling_enabled,
        "autoRollback": False,
        "launchTemplateVersion": launch_template_version,
        "desiredCapacity": desired_capacity,
        "minSize": min_size,
        "maxSize": max_size,
        "manualBaseline": mode == "MANUAL_BASELINE",
    }


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RolloutPlanError(f"unable to read JSON input: {path.name}") from exc
    if not isinstance(value, dict):
        raise RolloutPlanError(f"JSON input must be an object: {path.name}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_json", type=Path, help="terraform show -json saved plan")
    parser.add_argument("--contract", type=Path, required=True, help="sanitized Terraform rollout/restoration contract JSON")
    parser.add_argument("--refresh-only", action="store_true", help="require a no-op MANUAL_BASELINE drift-check plan")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan_result = validate_plan(_load(args.plan_json), refresh_only=args.refresh_only)
        contract_result = validate_contract(_load(args.contract), refresh_only=args.refresh_only)
    except RolloutPlanError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, separators=(",", ":")))
        return 1
    print(json.dumps({"passed": True, "plan": plan_result, "contract": contract_result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
