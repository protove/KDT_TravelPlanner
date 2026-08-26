#!/usr/bin/env python3
"""Validate the exact dev-eks destroy plan and prove retirement.

The verifier intentionally emits only safe counts/statuses. Raw Terraform
State, plan JSON and AWS responses remain in the caller's private run folder.
The saved plan must be delete-only and its managed address set must match the
captured dev-eks State scope exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class VerificationError(RuntimeError):
    """A fail-closed validation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_state_sha256(value: dict[str, Any]) -> str:
    normalized = dict(value)
    # Terraform can reorder or re-evaluate check_results without changing
    # managed resources, outputs, lineage or serial.
    normalized.pop("check_results", None)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label} is unreadable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be a JSON object")
    return value


def run_command(command: list[str], *, env: dict[str, str], allow: set[int] | None = None) -> subprocess.CompletedProcess[str]:
    allowed = allow or {0}
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    if result.returncode not in allowed:
        raise VerificationError(f"command failed: {command[0]} exit={result.returncode}")
    return result


def terraform_command(root: Path, args: list[str]) -> list[str]:
    return ["terraform", f"-chdir={root}", *args]


def managed_addresses(path: Path) -> list[str]:
    try:
        values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        raise VerificationError("managed-address snapshot is unreadable") from exc
    result = []
    for address in values:
        if not address or any(part == "data" for part in address.split(".")):
            continue
        result.append(address)
    return sorted(set(result))


def validate_lease(lease: dict[str, Any], state_before: Path, addresses_before: Path, account_id: str, region: str) -> tuple[list[str], dict[str, Any]]:
    required = {
        "schema_version",
        "lifecycle_run_id",
        "issued_at",
        "expires_at",
        "expected_account_sha256",
        "expected_region",
        "terraform_backend_key",
        "state_lineage",
        "state_serial",
        "state_sha256",
        "managed_address_sha256",
        "managed_address_count",
        "cluster_name",
        "helper_sha256",
        "forbidden_actions",
    }
    if lease.get("schema_version") != "dev-eks-cleanup-lease/v1" or not required.issubset(lease):
        raise VerificationError("cleanup lease schema is invalid")
    expected_account_hash = hashlib.sha256(account_id.encode()).hexdigest()
    if lease["expected_account_sha256"] != expected_account_hash or lease["expected_region"] != region:
        raise VerificationError("cleanup lease identity does not match the action target")
    if lease["terraform_backend_key"] != "dev-eks/terraform.tfstate":
        raise VerificationError("cleanup lease backend is outside dev-eks")
    try:
        issued_at = datetime.fromisoformat(str(lease["issued_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        expires_at = datetime.fromisoformat(str(lease["expires_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise VerificationError("cleanup lease timestamps are malformed") from exc
    if issued_at >= expires_at or expires_at.timestamp() <= time.time():
        raise VerificationError("cleanup lease has expired or has an invalid time window")
    if any(action in {"create", "update", "replace", "import", "state edit"} for action in lease.get("forbidden_actions", [])) is False:
        raise VerificationError("cleanup lease forbidden action list is incomplete")
    if sha256_file(state_before) != lease["state_sha256"]:
        raise VerificationError("cleanup lease State hash does not match the captured State")
    addresses = managed_addresses(addresses_before)
    address_hash = hashlib.sha256(("\n".join(addresses) + ("\n" if addresses else "")).encode()).hexdigest()
    if address_hash != lease["managed_address_sha256"] or len(addresses) != lease["managed_address_count"]:
        raise VerificationError("cleanup lease managed-address scope does not match the captured State")
    state = load_json(state_before, "State snapshot")
    if state.get("lineage") != lease["state_lineage"] or state.get("serial") != lease["state_serial"]:
        raise VerificationError("cleanup lease State lineage/serial does not match the captured State")
    return addresses, state


def current_scope(root: Path, env: dict[str, str], addresses: list[str], lease: dict[str, Any]) -> None:
    state = run_command(terraform_command(root, ["state", "pull"]), env=env).stdout
    try:
        value = json.loads(state)
    except json.JSONDecodeError as exc:
        raise VerificationError("current Terraform State is malformed") from exc
    if value.get("lineage") != lease["state_lineage"] or value.get("serial") != lease["state_serial"]:
        raise VerificationError("Terraform State changed after lease issuance")
    address_result = run_command(terraform_command(root, ["state", "list"]), env=env).stdout
    current = sorted(set(line.strip() for line in address_result.splitlines() if line.strip() and not any(part == "data" for part in line.strip().split("."))))
    if current != addresses:
        raise VerificationError("Terraform managed-address scope changed after lease issuance")


def validate_destroy_plan(plan: dict[str, Any], addresses: list[str]) -> dict[str, Any]:
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise VerificationError("destroy plan resource_changes is malformed")
    deletes: list[str] = []
    managed_count = 0
    for change in changes:
        if not isinstance(change, dict) or change.get("mode") != "managed":
            continue
        managed_count += 1
        address = change.get("address")
        actions = change.get("change", {}).get("actions")
        if not isinstance(address, str) or not isinstance(actions, list):
            raise VerificationError("destroy plan managed change is malformed")
        if actions != ["delete"]:
            raise VerificationError("destroy plan contains a non-delete managed action")
        deletes.append(address)
    if sorted(set(deletes)) != sorted(addresses):
        raise VerificationError("destroy plan delete-address set does not equal the lease scope")
    return {"managed_change_count": managed_count, "delete_address_count": len(deletes), "delete_only": True}


def create_and_apply_destroy(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    lease = load_json(args.lease, "cleanup lease")
    addresses, state = validate_lease(lease, args.state_before, args.addresses_before, args.expected_account_id, args.region)
    current_scope(args.terraform_root, env, addresses, lease)
    plan_result = run_command(
        terraform_command(args.terraform_root, ["plan", "-destroy", "-input=false", "-lock-timeout=5m", f"-out={args.destroy_plan}"]),
        env=env,
    )
    if plan_result.returncode != 0:
        raise VerificationError("destroy plan generation failed")
    plan_json_result = run_command(terraform_command(args.terraform_root, ["show", "-json", str(args.destroy_plan)]), env=env)
    try:
        plan = json.loads(plan_json_result.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("destroy plan JSON is malformed") from exc
    args.destroy_plan_json.write_text(json.dumps(plan, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.chmod(args.destroy_plan_json, 0o600)
    validation = validate_destroy_plan(plan, addresses)
    plan_hash = sha256_file(args.destroy_plan)
    apply_result = run_command(terraform_command(args.terraform_root, ["apply", "-input=false", str(args.destroy_plan)]), env=env)
    summary = {
        "schema_version": "dev-eks-destroy-summary/v1",
        "status": "applied",
        "delete_only": True,
        "managed_address_count": len(addresses),
        "plan_sha256": plan_hash,
        "plan_validation": validation,
        "terraform_apply_exit": apply_result.returncode,
        "state_serial_before": state.get("serial"),
    }
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(args.output, 0o600)
    return summary


def create_destroy_preview(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    lease = load_json(args.lease, "cleanup lease")
    addresses, state = validate_lease(lease, args.state_before, args.addresses_before, args.expected_account_id, args.region)
    current_scope(args.terraform_root, env, addresses, lease)
    run_command(
        terraform_command(args.terraform_root, ["plan", "-destroy", "-input=false", "-lock-timeout=5m", f"-out={args.destroy_plan}"]),
        env=env,
    )
    plan_json_result = run_command(terraform_command(args.terraform_root, ["show", "-json", str(args.destroy_plan)]), env=env)
    try:
        plan = json.loads(plan_json_result.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("destroy preview JSON is malformed") from exc
    args.destroy_plan_json.write_text(json.dumps(plan, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.chmod(args.destroy_plan_json, 0o600)
    validation = validate_destroy_plan(plan, addresses)
    summary = {
        "schema_version": "dev-eks-destroy-preview/v1",
        "status": "preview",
        "delete_only": True,
        "managed_address_count": len(addresses),
        "plan_sha256": sha256_file(args.destroy_plan),
        "plan_validation": validation,
        "terraform_apply_performed": False,
        "state_serial_before": state.get("serial"),
    }
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(args.output, 0o600)
    return summary


def aws_json(args: list[str], env: dict[str, str], *, allow: set[int] | None = None) -> dict[str, Any]:
    allowed = allow or {0}
    profile_args = [] if env.get("AWS_CREDENTIALS_BOOTSTRAPPED") == "true" and env.get("AWS_ACCESS_KEY_ID") else ["--profile", env["AWS_PROFILE"]]
    result = subprocess.run(
        ["aws", *profile_args, "--region", env["AWS_REGION"], *args],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode not in allowed:
        raise VerificationError(f"AWS inventory command failed: {args[0]} exit={result.returncode}")
    if result.returncode != 0:
        error_text = result.stderr.lower()
        if any(marker in error_text for marker in ("resourcenotfound", "nosuch", "not found", "notfound")):
            return {"_not_found": True}
        raise VerificationError(f"AWS inventory command returned an unexpected error: {args[0]}")
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise VerificationError("AWS inventory response is malformed") from exc
    if not isinstance(value, dict):
        raise VerificationError("AWS inventory response is not an object")
    return value


def resource_values(state: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for resource in state.get("resources", []):
        if not isinstance(resource, dict) or resource.get("type") != resource_type:
            continue
        for instance in resource.get("instances", []):
            if isinstance(instance, dict) and isinstance(instance.get("attributes"), dict):
                values.append(instance["attributes"])
    return values


def first_state_value(state: dict[str, Any], resource_type: str, key: str) -> str | None:
    for value in resource_values(state, resource_type):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def current_protected_state_fingerprint(root: Path, env: dict[str, str], key: str) -> dict[str, Any]:
    raw = run_command(terraform_command(root, ["state", "pull"]), env=env).stdout
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"protected State is malformed: {key}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("lineage"), str) or not isinstance(value.get("serial"), int):
        raise VerificationError(f"protected State schema is invalid: {key}")
    resources = value.get("resources")
    if not isinstance(resources, list):
        raise VerificationError(f"protected State resources are invalid: {key}")
    shape = [
        {
            "module": resource.get("module"),
            "type": resource.get("type"),
            "name": resource.get("name"),
            "mode": resource.get("mode"),
            "instance_count": len(resource.get("instances", [])) if isinstance(resource.get("instances"), list) else -1,
        }
        for resource in resources
        if isinstance(resource, dict)
    ]
    return {
        "key": key,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "lineage": value["lineage"],
        "serial": value["serial"],
        "resource_shape_sha256": hashlib.sha256(json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def verify_protected_state_fingerprints(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    if not args.protected_states_before:
        return {"status": "not_requested"}
    baseline = load_json(args.protected_states_before, "protected State fingerprints")
    expected_keys = ["dev-load-test/terraform.tfstate", "dev-runtime/terraform.tfstate", "dev/terraform.tfstate"]
    scopes = baseline.get("scopes")
    if baseline.get("schema_version") != "protected-state-fingerprint/v1" or not isinstance(scopes, list):
        raise VerificationError("protected State fingerprint schema is invalid")
    by_key = {entry.get("key"): entry for entry in scopes if isinstance(entry, dict)}
    if sorted(by_key) != expected_keys:
        raise VerificationError("protected State fingerprint scope is invalid")
    parent = args.protected_terraform_root.parent if args.protected_terraform_root else None
    if parent is None:
        raise VerificationError("protected State root is required for fingerprint verification")
    current_entries = []
    for key in expected_keys:
        root_name = key.split("/", 1)[0]
        root = parent / root_name
        current_entries.append(current_protected_state_fingerprint(root, env, key))
    baseline_entries = [by_key[key] for key in expected_keys]
    baseline_semantic = [
        {field: entry.get(field) for field in ("key", "lineage", "serial", "resource_shape_sha256")}
        for entry in baseline_entries
    ]
    current_semantic = [
        {field: entry.get(field) for field in ("key", "lineage", "serial", "resource_shape_sha256")}
        for entry in current_entries
    ]
    if current_semantic != baseline_semantic:
        raise VerificationError("protected State semantic fingerprints changed")
    raw_changed = [
        key
        for key, before, after in zip(expected_keys, baseline_entries, current_entries)
        if before.get("raw_sha256") != after.get("raw_sha256")
    ]
    return {
        "status": "unchanged",
        "comparison_basis": "lineage_serial_resource_shape",
        "scope_count": len(current_entries),
        "keys": expected_keys,
        "raw_sha256_differences": raw_changed,
    }


def tagged_elb_resource_count(
    env: dict[str, str],
    describe_operation: str,
    collection_key: str,
    arn_key: str,
    cluster_name: str,
) -> int:
    resources = aws_json(["elbv2", describe_operation, "--output", "json"], env).get(collection_key, [])
    count = 0
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        arn = resource.get(arn_key)
        if not isinstance(arn, str) or not arn:
            continue
        tags = aws_json(["elbv2", "describe-tags", "--resource-arns", arn, "--output", "json"], env, allow={0, 254})
        tag_descriptions = tags.get("TagDescriptions") or [{}]
        tag_values = {
            tag.get("Key"): tag.get("Value")
            for tag in tag_descriptions[0].get("Tags", [])
            if isinstance(tag, dict)
        }
        if tag_values.get("elbv2.k8s.aws/cluster") == cluster_name and tag_values.get("ingress.k8s.aws/stack") == "kdt-travelplanner-dev-eks":
            count += 1
    return count


def native_inventory(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    state = load_json(args.state_before, "State snapshot")
    result: dict[str, Any] = {"schema_version": "dev-eks-native-inventory/v1", "billable_residuals": [], "ambiguous_residuals": [], "allowed_terminal": []}

    cluster_name = args.cluster_name or first_state_value(state, "aws_eks_cluster", "name") or ""
    if cluster_name:
        cluster = aws_json(["eks", "describe-cluster", "--name", cluster_name, "--output", "json"], env, allow={0, 254})
        if cluster.get("cluster"):
            result["billable_residuals"].append("eks_cluster")
        nodegroup_names = sorted(
            {
                value.get("node_group_name")
                for value in resource_values(state, "aws_eks_node_group")
                if isinstance(value.get("node_group_name"), str) and value.get("node_group_name")
            }
        )
        nodegroup_count = 0
        for nodegroup_name in nodegroup_names:
            nodegroup = aws_json(
                [
                    "eks",
                    "describe-nodegroup",
                    "--cluster-name",
                    cluster_name,
                    "--nodegroup-name",
                    nodegroup_name,
                    "--output",
                    "json",
                ],
                env,
                allow={0, 254},
            )
            if nodegroup.get("nodegroup"):
                nodegroup_count += 1
        result["eks_nodegroup_count"] = nodegroup_count
        if nodegroup_count:
            result["billable_residuals"].append("eks_nodegroups")
    else:
        result["ambiguous_residuals"].append("eks_cluster_identity")

    instances = aws_json(["ec2", "describe-instances", "--filters", "Name=tag:Stack,Values=dev-eks", "Name=instance-state-name,Values=pending,running,stopping,stopped", "--output", "json"], env)
    instance_count = sum(len(reservation.get("Instances", [])) for reservation in instances.get("Reservations", []) if isinstance(reservation, dict))
    result["ec2_active_instance_count"] = instance_count
    if instance_count:
        result["billable_residuals"].append("ec2_instances")

    volumes = aws_json(["ec2", "describe-volumes", "--filters", "Name=tag:Stack,Values=dev-eks", "Name=status,Values=creating,available,in-use,deleting", "--output", "json"], env)
    volume_count = len(volumes.get("Volumes", []))
    result["ebs_active_volume_count"] = volume_count
    if volume_count:
        result["billable_residuals"].append("ebs_volumes")

    nat = aws_json(["ec2", "describe-nat-gateways", "--filter", "Name=tag:Stack,Values=dev-eks", "Name=state,Values=pending,available,deleting,failed", "--output", "json"], env)
    nat_count = len(nat.get("NatGateways", []))
    result["nat_gateway_count"] = nat_count
    if nat_count:
        result["billable_residuals"].append("nat_gateway")

    addresses = aws_json(["ec2", "describe-addresses", "--filters", "Name=tag:Stack,Values=dev-eks", "--output", "json"], env)
    eip_count = len(addresses.get("Addresses", []))
    result["eip_count"] = eip_count
    if eip_count:
        result["billable_residuals"].append("elastic_ip")

    db_id = args.database_identifier or first_state_value(state, "aws_db_instance", "identifier")
    if db_id:
        db = aws_json(["rds", "describe-db-instances", "--db-instance-identifier", db_id, "--output", "json"], env, allow={0, 254})
        if db.get("DBInstances"):
            result["billable_residuals"].append("rds_instance")
        snapshots = aws_json(["rds", "describe-db-snapshots", "--db-instance-identifier", db_id, "--output", "json"], env, allow={0, 254})
        if snapshots.get("DBSnapshots"):
            result["billable_residuals"].append("rds_snapshot")
    else:
        result["ambiguous_residuals"].append("rds_identity")

    redis_id = args.redis_replication_group_id or first_state_value(state, "aws_elasticache_replication_group", "replication_group_id")
    if redis_id:
        redis = aws_json(["elasticache", "describe-replication-groups", "--replication-group-id", redis_id, "--output", "json"], env, allow={0, 254})
        if redis.get("ReplicationGroups"):
            result["billable_residuals"].append("redis_replication_group")
        redis_snapshots = aws_json(["elasticache", "describe-snapshots", "--replication-group-id", redis_id, "--output", "json"], env, allow={0, 254})
        if redis_snapshots.get("Snapshots"):
            result["billable_residuals"].append("redis_snapshot")
    else:
        result["ambiguous_residuals"].append("redis_identity")

    alb_count = tagged_elb_resource_count(env, "describe-load-balancers", "LoadBalancers", "LoadBalancerArn", cluster_name)
    result["owned_alb_count"] = alb_count
    if alb_count:
        result["billable_residuals"].append("controller_alb")

    target_group_count = tagged_elb_resource_count(env, "describe-target-groups", "TargetGroups", "TargetGroupArn", cluster_name)
    result["owned_target_group_count"] = target_group_count
    if target_group_count:
        result["billable_residuals"].append("controller_target_groups")

    controller_sgs = aws_json(
        [
            "ec2",
            "describe-security-groups",
            "--filters",
            "Name=tag:elbv2.k8s.aws/cluster,Values=" + cluster_name,
            "Name=tag:ingress.k8s.aws/stack,Values=kdt-travelplanner-dev-eks",
            "--output",
            "json",
        ],
        env,
    )
    controller_sg_count = len(controller_sgs.get("SecurityGroups", []))
    result["owned_controller_security_group_count"] = controller_sg_count
    if controller_sg_count:
        result["billable_residuals"].append("controller_security_groups")

    if args.monitoring_bucket:
        profile_args = [] if env.get("AWS_CREDENTIALS_BOOTSTRAPPED") == "true" and env.get("AWS_ACCESS_KEY_ID") else ["--profile", env["AWS_PROFILE"]]
        bucket_check = subprocess.run(["aws", *profile_args, "--region", env["AWS_REGION"], "s3api", "head-bucket", "--bucket", args.monitoring_bucket], env=env, capture_output=True, text=True)
        if bucket_check.returncode == 0:
            result["billable_residuals"].append("monitoring_s3_bucket")
        elif not any(marker in bucket_check.stderr.lower() for marker in ("nosuchbucket", "notfound", "not found", "404")):
            result["ambiguous_residuals"].append("monitoring_s3_bucket")

    if args.parameter_name:
        parameter = aws_json(["ssm", "get-parameter", "--name", args.parameter_name, "--output", "json"], env, allow={0, 254})
        if parameter.get("Parameter"):
            result["billable_residuals"].append("ssm_parameter")

    log_group_name = f"/aws/eks/{cluster_name}/cluster"
    log_groups = aws_json(["logs", "describe-log-groups", "--log-group-name-prefix", log_group_name, "--output", "json"], env)
    if any(group.get("logGroupName") == log_group_name for group in log_groups.get("logGroups", []) if isinstance(group, dict)):
        result["billable_residuals"].append("cloudwatch_log_group")

    key_states: list[str] = []
    for value in resource_values(state, "aws_kms_key"):
        key_id = value.get("key_id") or value.get("id")
        if not isinstance(key_id, str) or not key_id:
            continue
        key = aws_json(["kms", "describe-key", "--key-id", key_id, "--output", "json"], env, allow={0, 254})
        metadata = key.get("KeyMetadata", {})
        state_name = metadata.get("KeyState")
        if state_name == "PendingDeletion":
            key_states.append("PendingDeletion")
            result["allowed_terminal"].append("kms_key_pending_deletion")
        elif state_name:
            result["billable_residuals"].append("kms_key_active")
    result["kms_key_states"] = key_states

    if args.protected_state_before:
        before_value = load_json(args.protected_state_before, "protected State snapshot")
        current = run_command(terraform_command(args.protected_terraform_root, ["state", "pull"]), env=env).stdout
        try:
            current_value = json.loads(current)
        except json.JSONDecodeError as exc:
            raise VerificationError("current protected Terraform State is malformed") from exc
        before_hash = stable_state_sha256(before_value)
        current_hash = stable_state_sha256(current_value)
        result["protected_state_semantic_sha256_before"] = before_hash
        result["protected_state_semantic_sha256_after"] = current_hash
        result["protected_state_unchanged"] = before_hash == current_hash
        if before_hash != current_hash:
            result["ambiguous_residuals"].append("protected_dev_state_changed")

    result["protected_states"] = verify_protected_state_fingerprints(args, env)

    result["billable_residual_count"] = len(result["billable_residuals"])
    result["ambiguous_residual_count"] = len(result["ambiguous_residuals"])
    if result["billable_residual_count"] or result["ambiguous_residual_count"]:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(args.output, 0o600)
        raise VerificationError("native inventory found billable or ambiguous dev-eks residuals")
    return result


def verify_retirement(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    lease = load_json(args.lease, "cleanup lease")
    validate_lease(lease, args.state_before, args.addresses_before, args.expected_account_id, args.region)
    current_state = run_command(terraform_command(args.terraform_root, ["state", "list"]), env=env).stdout
    if current_state.strip():
        raise VerificationError("Terraform State is not empty after destroy")
    destroy_check = subprocess.run(terraform_command(args.terraform_root, ["plan", "-destroy", "-input=false", "-detailed-exitcode"]), env=env, capture_output=True, text=True)
    if destroy_check.returncode != 0:
        raise VerificationError(f"destroy-mode no-change check returned {destroy_check.returncode}")
    inventory = native_inventory(args, env)
    result = {"schema_version": "dev-eks-retirement-proof/v1", "state_empty": True, "destroy_mode_exit": destroy_check.returncode, "native_inventory": inventory}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(args.output, 0o600)
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preview", "apply-destroy", "verify"), required=True)
    parser.add_argument("--terraform-root", type=Path, required=True)
    parser.add_argument("--aws-profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--lease", type=Path, required=True)
    parser.add_argument("--state-before", type=Path, required=True)
    parser.add_argument("--addresses-before", type=Path, required=True)
    parser.add_argument("--destroy-plan", type=Path)
    parser.add_argument("--destroy-plan-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cluster-name")
    parser.add_argument("--database-identifier")
    parser.add_argument("--redis-replication-group-id")
    parser.add_argument("--monitoring-bucket")
    parser.add_argument("--parameter-name")
    parser.add_argument("--protected-state-before", type=Path)
    parser.add_argument("--protected-states-before", type=Path)
    parser.add_argument("--protected-terraform-root", type=Path)
    args = parser.parse_args(argv)
    if not args.expected_account_id.isdigit() or len(args.expected_account_id) != 12:
        parser.error("--expected-account-id must be 12 digits")
    if args.mode in {"preview", "apply-destroy"} and not all((args.destroy_plan, args.destroy_plan_json)):
        parser.error(f"{args.mode} requires --destroy-plan and --destroy-plan-json")
    if args.protected_state_before and not args.protected_terraform_root:
        parser.error("--protected-state-before requires --protected-terraform-root")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    env = os.environ.copy()
    if os.environ.get("AWS_CREDENTIALS_BOOTSTRAPPED") == "true" and os.environ.get("AWS_ACCESS_KEY_ID"):
        env.pop("AWS_PROFILE", None)
        env["AWS_CREDENTIALS_BOOTSTRAPPED"] = "true"
    else:
        env["AWS_PROFILE"] = args.aws_profile
    env["AWS_REGION"] = args.region
    env["AWS_DEFAULT_REGION"] = args.region
    try:
        if not args.terraform_root.is_dir() or args.terraform_root.name != "dev-eks":
            raise VerificationError("Terraform root is not the dev-eks environment")
        if args.mode == "preview":
            create_destroy_preview(args, env)
        elif args.mode == "apply-destroy":
            create_and_apply_destroy(args, env)
        else:
            verify_retirement(args, env)
    except VerificationError as error:
        print(f"status=failed reason={error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
