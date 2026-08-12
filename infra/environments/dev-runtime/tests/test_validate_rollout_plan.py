from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "validate-rollout-plan.py"
SPEC = importlib.util.spec_from_file_location("validate_rollout_plan", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


IMAGE_A = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:" + "a" * 64
IMAGE_B = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:" + "b" * 64


def resource(address: str, actions: list[str]) -> dict:
    return {"address": address, "change": {"actions": actions}}


def normal_contract(**overrides: object) -> dict:
    contract = {
        "mode": "NORMAL",
        "minHealthyPercentage": 100,
        "maxHealthyPercentage": 200,
        "checkpointPercentages": [],
        "scalingPolicyEnabled": True,
        "autoRollback": False,
        "launchTemplateVersionRef": "7",
        "desiredCapacity": 2,
        "minSize": 2,
        "maxSize": 4,
        "normalBackendImageUri": IMAGE_A,
        "capacityRestored": False,
    }
    contract.update(overrides)
    return contract


def test_plan_allows_only_backend_rollout_changes() -> None:
    result = MODULE.validate_plan(
        {
            "resource_changes": [
                resource("module.backend_service.aws_launch_template.backend", ["update"]),
                resource("module.backend_service.aws_autoscaling_group.backend", ["update"]),
                resource("module.backend_service.aws_autoscaling_policy.cpu[0]", ["delete"]),
                resource("terraform_data.backend_image_contract", ["update"]),
                resource("aws_db_instance.backend", ["no-op"]),
            ]
        }
    )
    assert result["passed"] is True
    assert len(result["changedResources"]) == 4


@pytest.mark.parametrize(
    "address,actions",
    [
        ("aws_db_instance.backend", ["delete"]),
        ("aws_elasticache_replication_group.backend", ["create", "delete"]),
        ("aws_nat_gateway.this", ["delete"]),
        ("module.monitoring_ec2.aws_instance.this", ["delete"]),
        ("module.backend_service.aws_autoscaling_group.backend", ["create", "delete"]),
        ("module.backend_service.aws_autoscaling_policy.cpu[1]", ["delete"]),
    ],
)
def test_plan_rejects_forbidden_destructive_actions(address: str, actions: list[str]) -> None:
    with pytest.raises(MODULE.RolloutPlanError, match="forbidden"):
        MODULE.validate_plan({"resource_changes": [resource(address, actions)]})


def test_refresh_only_restore_requires_no_actions() -> None:
    with pytest.raises(MODULE.RolloutPlanError, match="no resource actions"):
        MODULE.validate_plan(
            {
                "resource_changes": [
                    resource("module.backend_service.aws_autoscaling_group.backend", ["update"])
                ]
            },
            refresh_only=True,
        )


def test_normal_contract_preserves_default_invariant() -> None:
    result = MODULE.validate_contract(normal_contract())
    assert result == {
        "mode": "NORMAL",
        "minHealthyPercentage": 100,
        "maxHealthyPercentage": 200,
        "checkpointPercentages": [],
        "scalingPolicyEnabled": True,
        "autoRollback": False,
        "launchTemplateVersion": "7",
        "desiredCapacity": 2,
        "minSize": 2,
        "maxSize": 4,
        "manualBaseline": False,
    }


def test_experiment_contract_requires_checkpoint_and_scaling_disabled() -> None:
    result = MODULE.validate_contract(
        normal_contract(
            mode="EXPERIMENT",
            maxHealthyPercentage=150,
            checkpointPercentages=[50, 100],
            scalingPolicyEnabled=False,
        )
    )
    assert result["manualBaseline"] is False
    with pytest.raises(MODULE.RolloutPlanError, match="experiment/fault"):
        MODULE.validate_contract(normal_contract(mode="EXPERIMENT", maxHealthyPercentage=200))


def test_fault_contract_binds_distinct_digest() -> None:
    result = MODULE.validate_contract(
        normal_contract(
            mode="FAULT",
            maxHealthyPercentage=150,
            checkpointPercentages=[50],
            scalingPolicyEnabled=False,
            faultBackendImageUri=IMAGE_B,
        )
    )
    assert result["mode"] == "FAULT"
    with pytest.raises(MODULE.RolloutPlanError, match="distinct"):
        MODULE.validate_contract(
            normal_contract(
                mode="FAULT",
                maxHealthyPercentage=150,
                checkpointPercentages=[50],
                scalingPolicyEnabled=False,
                faultBackendImageUri=IMAGE_A,
            )
        )


def test_manual_baseline_requires_exact_restore_digest_and_refresh_only() -> None:
    contract = normal_contract(
        mode="MANUAL_BASELINE",
        restoreBackendImageUri=IMAGE_A,
    )
    result = MODULE.validate_contract(contract, refresh_only=True)
    assert result["manualBaseline"] is True
    with pytest.raises(MODULE.RolloutPlanError, match="identical"):
        MODULE.validate_contract(
            normal_contract(mode="MANUAL_BASELINE", restoreBackendImageUri=IMAGE_B)
        )


def test_terraform_contract_cannot_claim_capacity_was_restored() -> None:
    with pytest.raises(MODULE.RolloutPlanError, match="capacityRestored"):
        MODULE.validate_contract(normal_contract(capacityRestored=True))


def test_restoration_state_contract_is_accepted_for_refresh_only() -> None:
    result = MODULE.validate_contract(
        {
            "mode": "MANUAL_BASELINE",
            "status": "planned",
            "desiredCapacity": 2,
            "minSize": 2,
            "maxSize": 4,
            "launchTemplateVersion": "7",
            "normalImageDigest": IMAGE_A,
            "capacityRestored": False,
            "scalingPolicyEnabled": True,
            "autoRollback": False,
            "manualBaselineRequired": True,
        },
        refresh_only=True,
    )
    assert result["manualBaseline"] is True
