#!/usr/bin/env python3
"""Fail-closed B-02 adapter for one EKS managed-node replacement.

The comparison fault is one member of the approved managed node-group being
terminated while the node group's desired capacity remains 2.  This adapter
does the narrow target read and, only in ``execute`` mode with a run-bound
approval file, calls the Auto Scaling termination API with
``--no-should-decrement-desired-capacity``.  It does not address ALB Pod IPs,
write node-group desired state, or perform any post-fault operator action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Protocol, Sequence


CONTRACT_VERSION = "aws-b02-eks-node-replacement-v1"
APPROVED_REGION = "ap-northeast-2"
APPROVED_ENVIRONMENT = "dev-eks"
APPROVED_CLUSTER = "kdt-travelplanner-dev-eks"
APPROVED_NODE_GROUP = "kdt-travelplanner-dev-eks-nodes"
RUN_ID_PATTERN = re.compile(r"^(?:aws|scrum43)-b02-[A-Za-z0-9._-]{1,80}$")
ACCOUNT_PATTERN = re.compile(r"^[0-9]{12}$")
INSTANCE_PATTERN = re.compile(r"^i-[0-9a-f]{8,32}$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
ARN_PATTERN = re.compile(
    r"^arn:aws:elasticloadbalancing:(?P<region>[a-z0-9-]+):(?P<account>[0-9]{12}):"
    r"targetgroup/[A-Za-z0-9._-]{1,64}/[0-9a-f]{16,32}$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_APPROVER = re.compile(r"(?:AKIA|ASIA|aws_secret|password|token|secret|[0-9]{12})", re.I)


class B02EksActionError(RuntimeError):
    """A sanitized contract or AWS adapter error."""


class AwsPort(Protocol):
    def read_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]: ...

    def mutate_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]: ...


class AwsCliPort:
    def __init__(self, *, profile: str | None = None) -> None:
        self.profile = profile

    def _run(self, service: str, operation: str, arguments: Sequence[str], *, mutate: bool) -> Mapping[str, Any]:
        command = ["aws", service, operation, *arguments]
        if self.profile:
            command += ["--profile", self.profile]
        command += ["--output", "json"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            action = "mutation" if mutate else "read-only call"
            raise B02EksActionError(f"AWS {action} failed for {service}:{operation}")
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as error:
            raise B02EksActionError(f"AWS {service}:{operation} returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise B02EksActionError(f"AWS {service}:{operation} returned a non-object response")
        return payload

    def read_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]:
        return self._run(service, operation, arguments, mutate=False)

    def mutate_json(self, service: str, operation: str, arguments: Sequence[str]) -> Mapping[str, Any]:
        return self._run(service, operation, arguments, mutate=True)


class B02EksRequest(NamedTuple):
    run_id: str
    expected_account_id: str
    region: str
    environment: str
    cluster_name: str
    node_group_name: str
    instance_id: str
    target_group_arn: str | None
    evidence_root: Path


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise B02EksActionError(message)


def _single(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, list) and len(value) == 1 and isinstance(value[0], Mapping), f"AWS response must contain exactly one {label}")
    return value[0]


def _tags(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    return {
        str(item.get("Key")): str(item.get("Value"))
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("Key"), str) and isinstance(item.get("Value"), str)
    }


def validate_request(request: B02EksRequest) -> None:
    _require(RUN_ID_PATTERN.fullmatch(request.run_id) is not None, "--run-id must use the aws/scrum43-b02 prefix")
    _require(ACCOUNT_PATTERN.fullmatch(request.expected_account_id) is not None, "--expected-account-id must be exactly 12 digits")
    _require(request.region == APPROVED_REGION, "B-02 EKS is approved only in ap-northeast-2")
    _require(request.environment == APPROVED_ENVIRONMENT, "B-02 EKS is approved only in dev-eks")
    _require(request.cluster_name == APPROVED_CLUSTER and NAME_PATTERN.fullmatch(request.cluster_name) is not None, "cluster is outside the approved dev-eks boundary")
    _require(request.node_group_name == APPROVED_NODE_GROUP and NAME_PATTERN.fullmatch(request.node_group_name) is not None, "node group is outside the approved dev-eks boundary")
    _require(INSTANCE_PATTERN.fullmatch(request.instance_id) is not None, "--instance-id must be an EC2 instance ID")
    if request.target_group_arn:
        match = ARN_PATTERN.fullmatch(request.target_group_arn)
        _require(match is not None, "--target-group-arn is invalid")
        _require(match.group("region") == request.region and match.group("account") == request.expected_account_id, "target group account/region does not match the approved target")
    _require(not request.evidence_root.exists() or request.evidence_root.is_dir(), "--evidence-root must be a directory")


def _target_health_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"targetType": "ip", "targetCount": None, "healthyTargetCount": None, "rawStored": False}
    descriptions = payload.get("TargetHealthDescriptions", [])
    _require(isinstance(descriptions, list), "target health response is malformed")
    states: list[str] = []
    for item in descriptions:
        target = item.get("Target") if isinstance(item, Mapping) else None
        target_id = target.get("Id") if isinstance(target, Mapping) else None
        _require(isinstance(target_id, str) and "." in target_id, "EKS ALB targets must be Pod IPs, never instance IDs")
        state = item.get("TargetHealth", {}).get("State") if isinstance(item.get("TargetHealth"), Mapping) else None
        if isinstance(state, str):
            states.append(state)
    return {
        "targetType": "ip",
        "targetCount": len(states),
        "healthyTargetCount": sum(state == "healthy" for state in states),
        "states": {state: states.count(state) for state in sorted(set(states))},
        "rawStored": False,
    }


def read_target_snapshot(request: B02EksRequest, aws: AwsPort) -> dict[str, Any]:
    validate_request(request)
    identity = aws.read_json("sts", "get-caller-identity", ["--region", request.region])
    _require(identity.get("Account") == request.expected_account_id, "observed AWS account does not match --expected-account-id")

    node_payload = aws.read_json("eks", "describe-nodegroup", ["--cluster-name", request.cluster_name, "--nodegroup-name", request.node_group_name, "--region", request.region])
    node = _single(node_payload.get("nodegroup") if isinstance(node_payload, Mapping) else None, "EKS node group") if isinstance(node_payload.get("nodegroup"), list) else (node_payload.get("nodegroup") or {})
    _require(isinstance(node, Mapping), "EKS node group response is malformed")
    _require(node.get("clusterName") == request.cluster_name and node.get("nodegroupName") == request.node_group_name and node.get("status") == "ACTIVE", "EKS node group identity/status does not match the approved target")
    scaling = node.get("scalingConfig") if isinstance(node.get("scalingConfig"), Mapping) else {}
    _require((scaling.get("minSize"), scaling.get("desiredSize"), scaling.get("maxSize")) == (2, 2, 4), "EKS node group capacity must be 2/2/4")
    asgs = (node.get("resources") or {}).get("autoScalingGroups", []) if isinstance(node.get("resources"), Mapping) else []
    _require(isinstance(asgs, list) and len(asgs) == 1 and isinstance(asgs[0], Mapping) and isinstance(asgs[0].get("name"), str), "EKS node group must expose exactly one backing ASG")
    asg_name = str(asgs[0]["name"])

    asg_payload = aws.read_json("autoscaling", "describe-auto-scaling-groups", ["--auto-scaling-group-names", asg_name, "--region", request.region])
    group = _single(asg_payload.get("AutoScalingGroups"), "backing ASG")
    _require(group.get("AutoScalingGroupName") == asg_name, "backing ASG identity changed")
    _require((group.get("MinSize"), group.get("DesiredCapacity"), group.get("MaxSize")) == (2, 2, 4), "backing ASG capacity must be 2/2/4")
    members = [item for item in group.get("Instances", []) if isinstance(item, Mapping) and item.get("InstanceId") == request.instance_id]
    _require(len(members) == 1, "requested node is not exactly one member of the managed node-group ASG")
    member = members[0]
    _require(member.get("LifecycleState") == "InService" and member.get("HealthStatus") == "Healthy", "requested node is not an InService/Healthy managed node")

    instance_payload = aws.read_json("ec2", "describe-instances", ["--instance-ids", request.instance_id, "--region", request.region])
    reservation = _single(instance_payload.get("Reservations"), "EC2 reservation")
    instance = _single(reservation.get("Instances"), "EC2 instance")
    _require(instance.get("InstanceId") == request.instance_id and (instance.get("State") or {}).get("Name") == "running", "requested node is not running")

    target_health = None
    if request.target_group_arn:
        target_health = aws.read_json("elbv2", "describe-target-health", ["--target-group-arn", request.target_group_arn, "--region", request.region])
        _target_health_summary(target_health)

    return {
        "clusterName": request.cluster_name,
        "nodeGroupName": request.node_group_name,
        "backingAutoScalingGroupName": asg_name,
        "instanceId": request.instance_id,
        "instanceType": instance.get("InstanceType"),
        "capacity": {"minSize": 2, "desiredSize": 2, "maxSize": 4},
        "lifecycleState": member.get("LifecycleState"),
        "healthStatus": member.get("HealthStatus"),
        "targetHealth": _target_health_summary(target_health),
        "nodeGroupStatus": node.get("status"),
    }


def _approval(path: Path) -> tuple[dict[str, Any], str]:
    _require(path.is_file(), "approval file is missing")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise B02EksActionError("approval file is not valid JSON") from error
    _require(isinstance(payload, Mapping) and payload.get("approved") is True, "B-02 EKS approval is not granted")
    approver = str(payload.get("approvedBy", ""))
    _require(approver and not FORBIDDEN_APPROVER.search(approver), "B-02 approval approver must not contain credentials or an AWS account ID")
    return dict(payload), digest


def _evidence_payload(request: B02EksRequest, snapshot: dict[str, Any], *, mode: str, approval: Mapping[str, Any] | None = None, approval_sha256: str | None = None, response_received: bool = False) -> dict[str, Any]:
    return {
        "contractVersion": CONTRACT_VERSION,
        "runId": request.run_id,
        "scenario": "B-02",
        "platform": "eks-managed-node",
        "mode": mode,
        "region": request.region,
        "environment": request.environment,
        "accountValidated": True,
        "target": snapshot,
        "mutation": {
            "operation": "terminate-instance-in-auto-scaling-group",
            "shouldDecrementDesiredCapacity": False,
            "allowed": mode == "execute",
            "performed": mode == "execute",
            "responseReceived": response_received,
        },
        "approval": ({"approved": True, "approvedBy": str(approval.get("approvedBy")), "sha256": approval_sha256} if approval else None),
        "restorationInvariants": {
            "oneNodeOnly": True,
            "instanceId": request.instance_id,
            "desiredSizeBefore": 2,
            "desiredSizeMustRemain": 2,
            "capacityMutation": "none",
            "postReplacementReadyNodeRequired": True,
            "postRescheduleReadyPodRequired": True,
        },
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def run_action(request: B02EksRequest, aws: AwsPort, *, mode: str, approval_file: Path | None = None) -> dict[str, Any]:
    _require(mode in {"plan", "execute"}, "mode must be plan or execute")
    snapshot = read_target_snapshot(request, aws)
    approval_payload = None
    approval_sha = None
    response_received = False
    if mode == "execute":
        _require(approval_file is not None, "--approval-file is required for execute")
        approval_payload, approval_sha = _approval(approval_file)
        response = aws.mutate_json(
            "autoscaling",
            "terminate-instance-in-auto-scaling-group",
            ["--instance-id", request.instance_id, "--no-should-decrement-desired-capacity", "--region", request.region],
        )
        _require(isinstance(response, Mapping), "B-02 EKS termination returned an invalid response")
        response_received = True
    result = _evidence_payload(request, snapshot, mode=mode, approval=approval_payload, approval_sha256=approval_sha, response_received=response_received)
    request.evidence_root.mkdir(parents=True, exist_ok=True)
    output = request.evidence_root / "b02-eks-action.json"
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if output.exists():
        _require(output.read_text(encoding="utf-8") == encoded, "existing B-02 EKS evidence differs; refusing overwrite")
    else:
        with output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "execute"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--region", default=APPROVED_REGION)
    parser.add_argument("--environment", default=APPROVED_ENVIRONMENT)
    parser.add_argument("--cluster-name", default=APPROVED_CLUSTER)
    parser.add_argument("--node-group-name", default=APPROVED_NODE_GROUP)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--target-group-arn", default=None)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, default=None)
    parser.add_argument("--profile", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    request = B02EksRequest(
        args.run_id, args.expected_account_id, args.region, args.environment,
        args.cluster_name, args.node_group_name, args.instance_id,
        args.target_group_arn, args.evidence_root.resolve(),
    )
    result = run_action(request, AwsCliPort(profile=args.profile), mode=args.mode, approval_file=args.approval_file.resolve() if args.approval_file else None)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except B02EksActionError as error:
        print(f"[b02-eks] blocked: {error}", file=sys.stderr)
        raise SystemExit(2)
