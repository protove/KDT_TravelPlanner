#!/usr/bin/env python3
"""Fail-closed B-02 one-instance replacement adapter.

The adapter is intentionally separate from the common Recovery orchestrator.
It validates one exact Backend ASG member and its ALB target before exposing
the only mutating operation used by B-02::

    autoscaling terminate-instance-in-auto-scaling-group
    --no-should-decrement-desired-capacity

``plan`` is read-only.  ``execute`` is never implied by a plan and requires a
separate, run-bound approval artifact.  The adapter does not discover a broad
set of instances, change ASG capacity, start an Instance Refresh, or invoke
Terraform.  It records only sanitized, idempotent evidence; raw AWS responses
and the AWS account ID are not written to the evidence bundle.

The module is deliberately dependency-free so the same contract can be tested
without credentials, boto3, Docker, or a live AWS account.  The CLI adapter
uses the AWS CLI as an external port and all unit tests inject a fake port.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Protocol, Sequence


CONTRACT_VERSION = "aws-b02-one-instance-replacement-v1"
APPROVED_SCENARIO = "B-02"
APPROVED_ENVIRONMENT = "dev-runtime"
APPROVED_REGION = "ap-northeast-2"
APPROVED_ASG_NAME = "kdt-travelplanner-dev-backend"
APPROVED_TARGET_GROUP_NAME = "kdt-travelplanner-dev-backend"
APPROVED_ASG_TAGS = {"Environment": "dev", "Service": "travel-planner-backend"}
APPROVED_INSTANCE_TAGS = {
    "Environment": "dev",
    "Service": "travel-planner-backend",
}
RUN_ID_PATTERN = re.compile(r"^(?:aws|scrum43)-b02-[A-Za-z0-9._-]{1,80}$")
ACCOUNT_ID_PATTERN = re.compile(r"^[0-9]{12}$")
INSTANCE_ID_PATTERN = re.compile(r"^i-[0-9a-f]{8,32}$")
ASG_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._:/+=,@-]{1,255}$")
REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+$")
TARGET_GROUP_ARN_PATTERN = re.compile(
    r"^arn:aws:elasticloadbalancing:(?P<region>[a-z0-9-]+):(?P<account>[0-9]{12}):"
    r"targetgroup/(?P<name>[A-Za-z0-9._-]{1,32})/(?P<id>[0-9a-f]{16,32})$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EVENT_PATTERN = re.compile(r"^T[0-5]$")
EVENT_ORDER = ("T0", "T1", "T2", "T3", "T4", "T5")
MUTATING_OPERATION = "terminate-instance-in-auto-scaling-group"
DENY_TOKENS = {
    "prod",
    "production",
    "runner",
    "monitoring",
    "rds",
    "redis",
}
REPLAY_TOP_LEVEL_KEYS = frozenset({
    "contractVersion", "scenario", "mode", "runId", "region", "environment",
    "accountValidated", "target", "restorationInvariants", "mutation", "approval",
    "status", "generatedAtUtc",
})
REPLAY_TARGET_KEYS = frozenset({
    "asgName", "instanceId", "targetGroupSuffix", "desiredCapacity", "minSize", "maxSize",
    "instanceState", "lifecycleState", "healthStatus", "targetHealth", "targetType",
    "launchTemplateId", "launchTemplateVersion", "asgTagContract", "instanceTagContract",
})
REPLAY_RESTORATION_KEYS = frozenset({
    "oneInstanceOnly", "instanceId", "desiredCapacityBefore", "desiredCapacityMustRemain",
    "minSizeBefore", "maxSizeBefore", "desiredCapacityMutation", "postReplacementHealthyTargetRequired",
    "postReplacementLaunchTemplateId", "postReplacementLaunchTemplateVersion",
})
REPLAY_MUTATION_KEYS = frozenset({
    "operation", "shouldDecrementDesiredCapacity", "allowed", "performed", "commandSha256", "responseReceived",
})
REPLAY_APPROVAL_KEYS = frozenset({"approved", "approvedBy"})


class B02ActionError(RuntimeError):
    """A sanitized B-02 contract or AWS adapter failure."""


class AwsPort(Protocol):
    """The narrow external port used by the adapter."""

    def read_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]: ...

    def mutate_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]: ...


class B02Request(NamedTuple):
    run_id: str
    expected_account_id: str
    region: str
    environment: str
    asg_name: str
    instance_id: str
    target_group_arn: str
    evidence_root: Path


class TargetSnapshot(NamedTuple):
    asg_name: str
    instance_id: str
    target_group_suffix: str
    desired_capacity: int
    min_size: int
    max_size: int
    instance_state: str
    lifecycle_state: str
    health_status: str
    target_health: str
    target_type: str
    launch_template_id: str | None
    launch_template_version: str | None
    asg_tag_contract: bool
    instance_tag_contract: bool


class AwsCliPort:
    """AWS CLI port with read/mutation methods kept visibly separate."""

    def __init__(self, *, profile: str | None = None):
        self.profile = profile

    def _run(self, service: str, operation: str, arguments: Sequence[str], *, mutate: bool) -> Mapping[str, Any]:
        command = ["aws", service, operation, *arguments]
        if self.profile:
            command.extend(["--profile", self.profile])
        command.extend(["--output", "json"])
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            # Never echo stderr: AWS CLI errors can contain resource/account
            # details.  Callers receive a stable, sanitized failure instead.
            action = "mutation" if mutate else "read-only call"
            raise B02ActionError(f"AWS {action} failed for {service}:{operation}")
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as error:
            raise B02ActionError(f"AWS {service}:{operation} returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise B02ActionError(f"AWS {service}:{operation} returned a non-object JSON response")
        return payload

    def read_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]:
        return self._run(service, operation, arguments, mutate=False)

    def mutate_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]:
        return self._run(service, operation, arguments, mutate=True)


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise B02ActionError(f"{field} must be a non-empty string")
    return value.strip()


def validate_request(request: B02Request) -> None:
    if not RUN_ID_PATTERN.fullmatch(request.run_id):
        raise B02ActionError("--run-id must use the aws-b02- or scrum43-b02- prefix and safe characters")
    if not ACCOUNT_ID_PATTERN.fullmatch(request.expected_account_id):
        raise B02ActionError("--expected-account-id must be exactly 12 digits")
    if not REGION_PATTERN.fullmatch(request.region):
        raise B02ActionError("--region is not a valid AWS region")
    if request.region != APPROVED_REGION:
        raise B02ActionError("B-02 is approved only in the ap-northeast-2 region")
    if request.environment != APPROVED_ENVIRONMENT:
        raise B02ActionError("B-02 is approved only for the dev-runtime environment")
    if not ASG_NAME_PATTERN.fullmatch(request.asg_name):
        raise B02ActionError("--asg-name contains unsafe characters")
    if request.asg_name != APPROVED_ASG_NAME:
        raise B02ActionError("--asg-name is not the approved dev Backend ASG")
    lowered_asg = request.asg_name.lower()
    if any(token in lowered_asg for token in DENY_TOKENS):
        # The approved backend name contains neither a Runner nor an
        # observability/data-service marker.  This blocks obvious copy/paste
        # mistakes before any AWS read is attempted.
        raise B02ActionError("--asg-name is outside the approved Backend ASG boundary")
    if not INSTANCE_ID_PATTERN.fullmatch(request.instance_id):
        raise B02ActionError("--instance-id must be an EC2 instance ID")
    match = TARGET_GROUP_ARN_PATTERN.fullmatch(request.target_group_arn)
    if not match:
        raise B02ActionError("--target-group-arn must be an exact target-group ARN")
    if match.group("region") != request.region:
        raise B02ActionError("target-group region does not match --region")
    if match.group("account") != request.expected_account_id:
        raise B02ActionError("target-group account does not match --expected-account-id")
    if match.group("name") != APPROVED_TARGET_GROUP_NAME:
        raise B02ActionError("target-group is not the approved dev Backend target group")
    if request.evidence_root.exists() and not request.evidence_root.is_dir():
        raise B02ActionError("--evidence-root must be a directory")


def _tags(items: Any) -> dict[str, str]:
    if not isinstance(items, list):
        return {}
    values: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key, value = item.get("Key"), item.get("Value")
        if isinstance(key, str) and isinstance(value, str):
            values[key] = value
    return values


def _tag_contract(tags: Mapping[str, str], expected: Mapping[str, str]) -> bool:
    return all(tags.get(key) == value for key, value in expected.items())


def _deny_tag_values(tags: Mapping[str, str]) -> bool:
    values = " ".join(f"{key}={value}" for key, value in tags.items()).lower()
    return any(re.search(rf"(?:^|[^a-z]){re.escape(token)}(?:$|[^a-z])", values) for token in DENY_TOKENS)


def _target_group_suffix(arn: str) -> str:
    match = TARGET_GROUP_ARN_PATTERN.fullmatch(arn)
    if not match:
        raise B02ActionError("target-group ARN is not valid")
    return f"targetgroup/{match.group('name')}/{match.group('id')}"


def _single_mapping(items: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
        raise B02ActionError(f"AWS response must contain exactly one {field}")
    return items[0]


def _launch_template(instance: Mapping[str, Any], group: Mapping[str, Any]) -> tuple[str | None, str | None]:
    value = instance.get("LaunchTemplate") or group.get("LaunchTemplate")
    if not isinstance(value, Mapping):
        return None, None
    identifier = value.get("LaunchTemplateId")
    version = value.get("Version")
    return (identifier if isinstance(identifier, str) else None, version if isinstance(version, str) else None)


def read_target_snapshot(request: B02Request, aws: AwsPort) -> TargetSnapshot:
    """Read and validate one exact ASG/instance/target tuple."""

    validate_request(request)
    identity = aws.read_json("sts", "get-caller-identity", ["--region", request.region])
    account = identity.get("Account")
    if account != request.expected_account_id:
        raise B02ActionError("observed AWS account does not match --expected-account-id")

    asg_payload = aws.read_json(
        "autoscaling",
        "describe-auto-scaling-groups",
        ["--auto-scaling-group-names", request.asg_name, "--region", request.region],
    )
    group = _single_mapping(asg_payload.get("AutoScalingGroups"), "Auto Scaling Group")
    if group.get("AutoScalingGroupName") != request.asg_name:
        raise B02ActionError("AWS returned a different Auto Scaling Group")
    asg_tags = _tags(group.get("Tags"))
    if not _tag_contract(asg_tags, APPROVED_ASG_TAGS) or _deny_tag_values(asg_tags):
        raise B02ActionError("ASG tags do not match the approved dev Backend contract")

    raw_instances = group.get("Instances")
    if not isinstance(raw_instances, list):
        raise B02ActionError("ASG response has no instance membership list")
    members = [item for item in raw_instances if isinstance(item, Mapping) and item.get("InstanceId") == request.instance_id]
    if len(members) != 1:
        raise B02ActionError("requested instance is not exactly one member of the requested ASG")
    member = members[0]
    lifecycle_state = member.get("LifecycleState")
    health_status = member.get("HealthStatus")
    if lifecycle_state != "InService" or health_status != "Healthy":
        raise B02ActionError("requested instance is not an InService/Healthy ASG member")

    instance_payload = aws.read_json(
        "ec2",
        "describe-instances",
        ["--instance-ids", request.instance_id, "--region", request.region],
    )
    reservation = _single_mapping(instance_payload.get("Reservations"), "EC2 reservation")
    instance = _single_mapping(reservation.get("Instances"), "EC2 instance")
    if instance.get("InstanceId") != request.instance_id or instance.get("State", {}).get("Name") != "running":
        raise B02ActionError("requested EC2 instance is not the running target")
    instance_tags = _tags(instance.get("Tags"))
    if not _tag_contract(instance_tags, APPROVED_INSTANCE_TAGS) or _deny_tag_values(instance_tags):
        raise B02ActionError("instance tags do not match the approved dev Backend contract")
    if instance_tags.get("aws:autoscaling:groupName") != request.asg_name:
        raise B02ActionError("instance aws:autoscaling:groupName tag does not match the requested ASG")

    group_payload = aws.read_json(
        "elbv2",
        "describe-target-groups",
        ["--target-group-arns", request.target_group_arn, "--region", request.region],
    )
    target_group = _single_mapping(group_payload.get("TargetGroups"), "target group")
    if target_group.get("TargetGroupArn") != request.target_group_arn or target_group.get("TargetType") != "instance":
        raise B02ActionError("target group is not the exact approved EC2 target group")

    health_payload = aws.read_json(
        "elbv2",
        "describe-target-health",
        ["--target-group-arn", request.target_group_arn, "--region", request.region],
    )
    descriptions = health_payload.get("TargetHealthDescriptions")
    if not isinstance(descriptions, list):
        raise B02ActionError("target-group response has no health descriptions")
    matching = [
        item for item in descriptions
        if isinstance(item, Mapping)
        and isinstance(item.get("Target"), Mapping)
        and item["Target"].get("Id") == request.instance_id
    ]
    if len(matching) != 1:
        raise B02ActionError("requested instance is not exactly one target in the requested target group")
    target = matching[0]
    target_id = target.get("Target", {}).get("Id")
    target_port = target.get("Target", {}).get("Port")
    # The API does not echo target type in each description.  Instance IDs are
    # the explicit target-type proof for this adapter; IP/Lambda targets are
    # rejected by the EC2 ID contract before this point.
    if target.get("TargetHealth", {}).get("State") != "healthy":
        raise B02ActionError("requested target is not healthy immediately before B-02")
    if not isinstance(target_id, str) or target_id != request.instance_id:
        raise B02ActionError("requested target does not contain the exact EC2 instance ID")
    if not isinstance(target_port, int) or isinstance(target_port, bool) or not 1 <= target_port <= 65535:
        raise B02ActionError("requested target does not contain an EC2 target port")

    launch_template_id, launch_template_version = _launch_template(instance, group)
    desired = group.get("DesiredCapacity")
    minimum = group.get("MinSize")
    maximum = group.get("MaxSize")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (desired, minimum, maximum)):
        raise B02ActionError("ASG capacity values are invalid")
    if minimum < 1 or desired < minimum or maximum < desired:
        raise B02ActionError("ASG capacity bounds are invalid for one-instance replacement")

    return TargetSnapshot(
        asg_name=request.asg_name,
        instance_id=request.instance_id,
        target_group_suffix=_target_group_suffix(request.target_group_arn),
        desired_capacity=desired,
        min_size=minimum,
        max_size=maximum,
        instance_state="running",
        lifecycle_state=lifecycle_state,
        health_status=health_status,
        target_health="healthy",
        target_type="instance",
        launch_template_id=launch_template_id,
        launch_template_version=launch_template_version,
        asg_tag_contract=True,
        instance_tag_contract=True,
    )


def mutation_arguments(request: B02Request) -> list[str]:
    """Return the only approved mutation and make no-decrement explicit."""

    validate_request(request)
    return [
        "--instance-id",
        request.instance_id,
        "--no-should-decrement-desired-capacity",
        "--region",
        request.region,
    ]


def command_digest(request: B02Request, snapshot: TargetSnapshot) -> str:
    # Hash a canonical, sanitized command description.  The target-group ARN
    # is represented by its account-free suffix; Account IDs never enter the
    # evidence payload or this digest.
    payload = {
        "contractVersion": CONTRACT_VERSION,
        "scenario": APPROVED_SCENARIO,
        "runId": request.run_id,
        "region": request.region,
        "environment": request.environment,
        "asgName": request.asg_name,
        "instanceId": request.instance_id,
        "targetGroupSuffix": snapshot.target_group_suffix,
        "desiredCapacity": snapshot.desired_capacity,
        "minSize": snapshot.min_size,
        "maxSize": snapshot.max_size,
        "mutation": MUTATING_OPERATION,
        "shouldDecrementDesiredCapacity": False,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_detail(detail: str) -> str:
    if not isinstance(detail, str) or not detail.strip():
        raise B02ActionError("event detail must be non-empty")
    if len(detail) > 200 or any(char in detail for char in "\r\n"):
        raise B02ActionError("event detail must be at most 200 characters and single-line")
    if re.search(r"(?:AKIA|ASIA)[A-Z0-9]{16}|[0-9]{12}", detail):
        raise B02ActionError("event detail must not contain credentials or an AWS account ID")
    return detail.strip()


def _safe_approver(value: Any) -> str:
    """Validate an approver label without allowing credentials/account IDs."""

    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise B02ActionError("B-02 approval approver must be a non-empty short label")
    value = value.strip()
    if any(char in value for char in "\r\n"):
        raise B02ActionError("B-02 approval approver must be single-line")
    if re.search(r"(?:AKIA|ASIA)[A-Z0-9]{16}|[0-9]{12}", value):
        raise B02ActionError("B-02 approval approver must not contain credentials or an AWS account ID")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != set(expected):
        raise B02ActionError(f"{label} contains unexpected or missing fields")


def _safe_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    temporary.replace(path)


def _load_existing(path: Path, expected_digest: str) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise B02ActionError(f"existing evidence is unreadable: {path.name}") from error
    if not isinstance(payload, Mapping) or payload.get("contractVersion") != CONTRACT_VERSION:
        raise B02ActionError("existing evidence has an unexpected B-02 contract")
    mutation = payload.get("mutation")
    if not isinstance(mutation, Mapping) or mutation.get("commandSha256") != expected_digest:
        raise B02ActionError("existing B-02 evidence does not match the exact requested target")
    return payload


def _load_execute_replay(path: Path, request: B02Request) -> Mapping[str, Any] | None:
    """Return a prior execute result without re-reading a now-terminated target.

    A second invocation must remain read-only even after the original target
    has left the ASG.  The immutable request fields in the evidence bind the
    replay; a different target or run is rejected rather than reused.
    """

    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise B02ActionError(f"existing evidence is unreadable: {path.name}") from error
    if not isinstance(payload, Mapping) or payload.get("contractVersion") != CONTRACT_VERSION:
        raise B02ActionError("existing evidence has an unexpected B-02 contract")
    _require_exact_keys(payload, REPLAY_TOP_LEVEL_KEYS, "existing B-02 evidence")
    target = payload.get("target")
    if (
        payload.get("contractVersion") != CONTRACT_VERSION
        or payload.get("scenario") != APPROVED_SCENARIO
        or payload.get("mode") != "execute"
        or payload.get("runId") != request.run_id
        or payload.get("region") != request.region
        or payload.get("environment") != request.environment
        or payload.get("accountValidated") is not True
        or payload.get("status") != "EXECUTED"
        or not isinstance(target, Mapping)
    ):
        raise B02ActionError("existing B-02 evidence is not a completed execution record")
    snapshot = _snapshot_from_replay_payload(target, request)
    restoration = payload.get("restorationInvariants")
    if not isinstance(restoration, Mapping):
        raise B02ActionError("existing B-02 evidence restoration invariants are invalid")
    _require_exact_keys(restoration, REPLAY_RESTORATION_KEYS, "existing B-02 restoration invariants")
    if restoration != _restoration_invariants(snapshot):
        raise B02ActionError("existing B-02 evidence restoration invariants are invalid")
    mutation = payload.get("mutation")
    if (
        not isinstance(mutation, Mapping)
        or mutation.get("operation") != MUTATING_OPERATION
        or mutation.get("shouldDecrementDesiredCapacity") is not False
        or mutation.get("allowed") is not True
        or mutation.get("performed") is not True
        or mutation.get("responseReceived") is not True
        or mutation.get("commandSha256") != command_digest(request, snapshot)
    ):
        raise B02ActionError("existing B-02 evidence mutation contract is invalid")
    _require_exact_keys(mutation, REPLAY_MUTATION_KEYS, "existing B-02 mutation")
    approval = payload.get("approval")
    if (
        not isinstance(approval, Mapping)
        or approval.get("approved") is not True
    ):
        raise B02ActionError("existing B-02 evidence approval contract is invalid")
    _require_exact_keys(approval, REPLAY_APPROVAL_KEYS, "existing B-02 approval")
    _safe_approver(approval.get("approvedBy"))
    return payload


def _refuse_incomplete_execute_state(output_path: Path) -> None:
    """Fail closed after a mutation whose final evidence write was interrupted."""

    state_path = output_path.parent / "restoration-state.json"
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise B02ActionError("existing restoration-state.json is invalid") from error
    if isinstance(state, Mapping) and state.get("mode") == "execute":
        raise B02ActionError("an earlier B-02 mutation has incomplete evidence; reconcile before retrying")


def _snapshot_payload(snapshot: TargetSnapshot) -> dict[str, Any]:
    return {
        "asgName": snapshot.asg_name,
        "instanceId": snapshot.instance_id,
        "targetGroupSuffix": snapshot.target_group_suffix,
        "desiredCapacity": snapshot.desired_capacity,
        "minSize": snapshot.min_size,
        "maxSize": snapshot.max_size,
        "instanceState": snapshot.instance_state,
        "lifecycleState": snapshot.lifecycle_state,
        "healthStatus": snapshot.health_status,
        "targetHealth": snapshot.target_health,
        "targetType": snapshot.target_type,
        "launchTemplateId": snapshot.launch_template_id,
        "launchTemplateVersion": snapshot.launch_template_version,
        "asgTagContract": snapshot.asg_tag_contract,
        "instanceTagContract": snapshot.instance_tag_contract,
    }


def _snapshot_from_replay_payload(target: Mapping[str, Any], request: B02Request) -> TargetSnapshot:
    """Reconstruct the immutable pre-action snapshot for a read-only replay.

    Execute replay runs before any AWS read because the original instance may
    already have terminated. The evidence is therefore the only available
    source for replay validation and must be parsed strictly.
    """

    _require_exact_keys(target, REPLAY_TARGET_KEYS, "existing B-02 target snapshot")
    if target.get("asgName") != request.asg_name or target.get("instanceId") != request.instance_id:
        raise B02ActionError("existing B-02 evidence does not match the exact requested target")
    expected_suffix = _target_group_suffix(request.target_group_arn)
    if target.get("targetGroupSuffix") != expected_suffix:
        raise B02ActionError("existing B-02 evidence does not match the exact target group")
    expected_states = {
        "instanceState": "running",
        "lifecycleState": "InService",
        "healthStatus": "Healthy",
        "targetHealth": "healthy",
        "targetType": "instance",
    }
    if any(target.get(field) != expected for field, expected in expected_states.items()):
        raise B02ActionError("existing B-02 evidence has an invalid target health snapshot")
    if target.get("asgTagContract") is not True or target.get("instanceTagContract") is not True:
        raise B02ActionError("existing B-02 evidence has an invalid tag contract")

    capacities: list[int] = []
    for field in ("desiredCapacity", "minSize", "maxSize"):
        value = target.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise B02ActionError(f"existing B-02 evidence has an invalid {field}")
        capacities.append(value)
    desired, minimum, maximum = capacities
    if minimum < 1 or desired < minimum or maximum < desired:
        raise B02ActionError("existing B-02 evidence has invalid ASG capacity bounds")

    launch_template_id = target.get("launchTemplateId")
    if launch_template_id is not None and (
        not isinstance(launch_template_id, str)
        or not re.fullmatch(r"lt-[A-Za-z0-9]+", launch_template_id)
    ):
        raise B02ActionError("existing B-02 evidence has an invalid Launch Template ID")
    launch_template_version = target.get("launchTemplateVersion")
    if launch_template_version is not None and (
        not isinstance(launch_template_version, str)
        or not re.fullmatch(r"[0-9]+", launch_template_version)
    ):
        raise B02ActionError("existing B-02 evidence has an invalid Launch Template version")

    return TargetSnapshot(
        asg_name=request.asg_name,
        instance_id=request.instance_id,
        target_group_suffix=expected_suffix,
        desired_capacity=desired,
        min_size=minimum,
        max_size=maximum,
        instance_state="running",
        lifecycle_state="InService",
        health_status="Healthy",
        target_health="healthy",
        target_type="instance",
        launch_template_id=launch_template_id,
        launch_template_version=launch_template_version,
        asg_tag_contract=True,
        instance_tag_contract=True,
    )


def _restoration_invariants(snapshot: TargetSnapshot) -> dict[str, Any]:
    """Record what the post-replacement verifier must prove.

    These are requirements, not a claim that replacement has already
    completed.  Keeping them with both plan and execute evidence lets the
    Recovery exporter correlate T1-T5 with the exact capacity boundary.
    """

    return {
        "oneInstanceOnly": True,
        "instanceId": snapshot.instance_id,
        "desiredCapacityBefore": snapshot.desired_capacity,
        "desiredCapacityMustRemain": snapshot.desired_capacity,
        "minSizeBefore": snapshot.min_size,
        "maxSizeBefore": snapshot.max_size,
        "desiredCapacityMutation": "none",
        "postReplacementHealthyTargetRequired": True,
        "postReplacementLaunchTemplateId": snapshot.launch_template_id,
        "postReplacementLaunchTemplateVersion": snapshot.launch_template_version,
    }


def write_restoration_state(request: B02Request, snapshot: TargetSnapshot, *, mode: str) -> Path:
    """Write the sanitized state contract consumed by recovery evidence export."""

    path = request.evidence_root / "restoration-state.json"
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise B02ActionError("existing restoration-state.json is invalid") from error
        if not isinstance(existing, Mapping):
            raise B02ActionError("existing restoration-state.json must be a JSON object")
        existing_target = existing.get("target")
        if not isinstance(existing_target, Mapping):
            raise B02ActionError("existing restoration-state.json target is invalid")
        if (
            existing.get("contractVersion") != CONTRACT_VERSION
            or existing.get("runId") != request.run_id
            or existing_target.get("asgName") != snapshot.asg_name
            or existing_target.get("instanceId") != snapshot.instance_id
        ):
            raise B02ActionError("existing restoration-state.json is bound to a different target")
        # Once an execute state exists, a later plan must not overwrite the
        # evidence with a less authoritative pre-action state.
        if existing.get("mode") == "execute" and mode == "plan":
            return path
    payload = {
        "contractVersion": CONTRACT_VERSION,
        "scenario": APPROVED_SCENARIO,
        "mode": mode,
        "runId": request.run_id,
        "region": request.region,
        "environment": request.environment,
        "target": {
            "asgName": snapshot.asg_name,
            "instanceId": snapshot.instance_id,
            "targetGroupSuffix": snapshot.target_group_suffix,
        },
        "invariants": _restoration_invariants(snapshot),
        "status": "PENDING_VERIFICATION",
        "generatedAtUtc": _utc_now(),
    }
    _safe_json_write(path, payload)
    return path


def write_plan(request: B02Request, snapshot: TargetSnapshot, *, output_path: Path) -> Mapping[str, Any]:
    digest = command_digest(request, snapshot)
    existing = _load_existing(output_path, digest)
    if existing is not None:
        return existing
    write_restoration_state(request, snapshot, mode="plan")
    payload = {
        "contractVersion": CONTRACT_VERSION,
        "scenario": APPROVED_SCENARIO,
        "mode": "plan",
        "runId": request.run_id,
        "region": request.region,
        "environment": request.environment,
        "accountValidated": True,
        "target": _snapshot_payload(snapshot),
        "restorationInvariants": _restoration_invariants(snapshot),
        "mutation": {
            "operation": MUTATING_OPERATION,
            "shouldDecrementDesiredCapacity": False,
            "allowed": False,
            "commandSha256": digest,
        },
        "status": "PLANNED",
        "generatedAtUtc": _utc_now(),
    }
    _safe_json_write(output_path, payload)
    return payload


def _load_approval(path: Path, request: B02Request) -> Mapping[str, Any]:
    if not path.is_file():
        raise B02ActionError("--approval-file is required for execute and must exist")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise B02ActionError("--approval-file is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise B02ActionError("--approval-file must contain a JSON object")
    if payload.get("approved") is not True or payload.get("scenario") != APPROVED_SCENARIO:
        raise B02ActionError("B-02 approval artifact is not approved for this scenario")
    if payload.get("runId") != request.run_id or payload.get("asgName") != request.asg_name or payload.get("instanceId") != request.instance_id:
        raise B02ActionError("B-02 approval artifact is bound to a different run or target")
    if payload.get("environment") != request.environment or payload.get("region") != request.region:
        raise B02ActionError("B-02 approval artifact environment/region does not match")
    _safe_approver(payload.get("approvedBy"))
    return payload


def execute_action(
    request: B02Request,
    snapshot: TargetSnapshot,
    aws: AwsPort,
    *,
    approval_file: Path,
    output_path: Path,
) -> Mapping[str, Any]:
    digest = command_digest(request, snapshot)
    existing = _load_existing(output_path, digest)
    if existing is not None:
        # Replay is read-only.  In particular, never re-submit terminate on a
        # second invocation with the same run-bound evidence.
        return existing
    approval = _load_approval(approval_file, request)
    _refuse_incomplete_execute_state(output_path)
    # Persist the run-bound pre-action invariants before the mutation.  If the
    # AWS call fails, the pending state is still useful evidence; if writing
    # fails, no mutation is attempted.
    write_restoration_state(request, snapshot, mode="execute")
    response = aws.mutate_json(
        "autoscaling",
        MUTATING_OPERATION,
        mutation_arguments(request),
    )
    if not isinstance(response, Mapping):
        raise B02ActionError("B-02 mutation returned an invalid response")
    payload = {
        "contractVersion": CONTRACT_VERSION,
        "scenario": APPROVED_SCENARIO,
        "mode": "execute",
        "runId": request.run_id,
        "region": request.region,
        "environment": request.environment,
        "accountValidated": True,
        "target": _snapshot_payload(snapshot),
        "restorationInvariants": _restoration_invariants(snapshot),
        "mutation": {
            "operation": MUTATING_OPERATION,
            "shouldDecrementDesiredCapacity": False,
            "allowed": True,
            "performed": True,
            "commandSha256": digest,
            # Do not persist the raw API response; the response can contain
            # account/resource details and is not needed for the contract.
            "responseReceived": True,
        },
        "approval": {"approved": True, "approvedBy": _safe_approver(approval["approvedBy"])},
        "status": "EXECUTED",
        "generatedAtUtc": _utc_now(),
    }
    _safe_json_write(output_path, payload)
    return payload


def append_event(path: Path, request: B02Request, event: str, detail: str) -> Mapping[str, Any]:
    validate_request(request)
    if not EVENT_PATTERN.fullmatch(event):
        raise B02ActionError("event must be one of T0, T1, T2, T3, T4, or T5")
    safe_detail = _safe_detail(detail)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError
                existing.append(value)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise B02ActionError("existing B-02 operations evidence is invalid") from error
    for prior in existing:
        if prior.get("runId") == request.run_id and prior.get("event") == event:
            if prior.get("detail") != safe_detail or prior.get("instanceId") != request.instance_id:
                raise B02ActionError("event already exists with different immutable details")
            return prior
    prior_events = [item.get("event") for item in existing if item.get("event") in EVENT_ORDER]
    if prior_events:
        highest = max(EVENT_ORDER.index(name) for name in prior_events)
        requested = EVENT_ORDER.index(event)
        if requested != highest + 1:
            raise B02ActionError("T0-T5 events must be recorded in strict chronological order")
    elif event != "T0":
        raise B02ActionError("T0 must be recorded before the first B-02 event")
    record = {
        "ts": _utc_now(),
        "event": event,
        "detail": safe_detail,
        "actor": "aws-b02-adapter",
        "runId": request.run_id,
        "instanceId": request.instance_id,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return record


def _request_from_args(args: argparse.Namespace) -> B02Request:
    return B02Request(
        run_id=args.run_id,
        expected_account_id=args.expected_account_id,
        region=args.region,
        environment=args.environment,
        asg_name=args.asg_name,
        instance_id=args.instance_id,
        target_group_arn=args.target_group_arn,
        evidence_root=args.evidence_root,
    )


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--asg-name", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--target-group-arn", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--profile", default=None, help="AWS CLI profile; never written to evidence")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    plan = subparsers.add_parser("plan", help="read-only target validation and action plan")
    _common_parser(plan)
    plan.add_argument("--output", type=Path, default=None)
    execute = subparsers.add_parser("execute", help="explicitly approved one-instance replacement")
    _common_parser(execute)
    execute.add_argument("--approval-file", type=Path, required=True)
    execute.add_argument("--output", type=Path, default=None)
    event = subparsers.add_parser("event", help="append an idempotent T0-T5 operation event")
    _common_parser(event)
    event.add_argument("--event", required=True)
    event.add_argument("--detail", required=True)
    event.add_argument("--operations-file", type=Path, default=None)
    return parser.parse_args(argv)


def _default_output(request: B02Request, mode: str) -> Path:
    return request.evidence_root / ("b02-plan.json" if mode == "plan" else "b02-action.json")


def main(argv: Sequence[str] | None = None, *, aws: AwsPort | None = None) -> int:
    args = parse_args(argv)
    try:
        request = _request_from_args(args)
        validate_request(request)
        if args.mode == "event":
            output = args.operations_file or request.evidence_root / "operations.jsonl"
            record = append_event(output, request, args.event, args.detail)
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
            return 0
        output = args.output or _default_output(request, args.mode)
        if args.mode == "execute":
            replay = _load_execute_replay(output, request)
            if replay is not None:
                print(json.dumps(replay, ensure_ascii=False, sort_keys=True))
                return 0
            _refuse_incomplete_execute_state(output)
        port = aws or AwsCliPort(profile=args.profile)
        snapshot = read_target_snapshot(request, port)
        if args.mode == "plan":
            result = write_plan(request, snapshot, output_path=output)
        else:
            result = execute_action(request, snapshot, port, approval_file=args.approval_file, output_path=output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except B02ActionError as error:
        print(f"[b02] blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
