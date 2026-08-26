#!/usr/bin/env python3
"""Pure EKS target/evidence helpers for the AWS B-01 orchestrator.

The EC2 path resolves healthy ALB targets back to a Backend ASG.  That is
intentionally invalid for EKS because an ALB IP target is a Pod IP.  This
module keeps the EKS contract separate: it validates the managed node-group
backing ASG, records target health as Pod-IP health, and turns SSM kubectl
output into a small, non-secret evidence document.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from pathlib import Path
from typing import Any


NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
INSTANCE_ID_RE = re.compile(r"^i-[0-9a-f]{8,32}$")
ARN_RE = re.compile(r"^arn:aws:[A-Za-z0-9-]+:[A-Za-z0-9-]+:[0-9]{12}:.+$")


class EKSAdapterError(ValueError):
    """Raised when an EKS target does not satisfy the comparison contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EKSAdapterError(message)


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EKSAdapterError(f"invalid JSON fixture: {path}") from error
    _require(isinstance(payload, dict), f"JSON fixture must be an object: {path}")
    return payload


def _validate_name(value: str, label: str) -> None:
    _require(isinstance(value, str) and bool(NAME_RE.fullmatch(value)), f"{label} is not a safe Kubernetes/AWS name")


def resolve_node_group(
    describe_nodegroup: dict[str, Any],
    *,
    expected_cluster: str,
    expected_node_group: str,
) -> dict[str, Any]:
    """Validate and reduce ``eks describe-nodegroup`` to safe dimensions."""

    _validate_name(expected_cluster, "cluster name")
    _validate_name(expected_node_group, "node group name")
    nodegroup = describe_nodegroup.get("nodegroup")
    _require(isinstance(nodegroup, dict), "EKS describe-nodegroup has no nodegroup object")
    _require(nodegroup.get("clusterName") == expected_cluster, "EKS node group belongs to an unexpected cluster")
    _require(nodegroup.get("nodegroupName") == expected_node_group, "EKS node group name does not match the approved target")
    _require(nodegroup.get("status") == "ACTIVE", "EKS node group is not ACTIVE")
    scaling = nodegroup.get("scalingConfig") or {}
    shape = {
        "min": scaling.get("minSize"),
        "desired": scaling.get("desiredSize"),
        "max": scaling.get("maxSize"),
    }
    _require(shape == {"min": 2, "desired": 2, "max": 4}, f"EKS node group scaling must be 2/2/4, got {shape}")
    resources = nodegroup.get("resources") or {}
    asgs = resources.get("autoScalingGroups") or []
    _require(isinstance(asgs, list) and len(asgs) == 1, "EKS node group must expose exactly one backing ASG")
    asg_name = asgs[0].get("name") if isinstance(asgs[0], dict) else None
    _require(isinstance(asg_name, str) and asg_name, "EKS node group backing ASG name is missing")
    _require(not INSTANCE_ID_RE.fullmatch(asg_name), "EKS node group backing ASG cannot be an instance ID")
    return {
        "clusterName": expected_cluster,
        "nodeGroupName": expected_node_group,
        "status": nodegroup["status"],
        "version": nodegroup.get("version"),
        "capacityType": nodegroup.get("capacityType"),
        "scalingConfig": shape,
        "autoScalingGroupName": asg_name,
        "instanceTypes": list(nodegroup.get("instanceTypes") or []),
    }


def validate_alb_target_health(
    target_health: dict[str, Any],
    *,
    target_group_arn: str,
) -> dict[str, Any]:
    """Validate an ALB IP target group without treating Pod IPs as EC2 IDs."""

    _require(isinstance(target_group_arn, str) and ARN_RE.fullmatch(target_group_arn), "target group ARN is invalid")
    descriptions = target_health.get("TargetHealthDescriptions") or []
    _require(isinstance(descriptions, list), "target health response is malformed")
    states: list[str] = []
    for item in descriptions:
        target = item.get("Target") if isinstance(item, dict) else None
        target_id = target.get("Id") if isinstance(target, dict) else None
        _require(isinstance(target_id, str), "EKS ALB target is missing an IP target ID")
        try:
            address = ipaddress.ip_address(target_id)
        except ValueError as error:
            raise EKSAdapterError("EKS ALB target must be a Pod IP, never an EC2 instance ID") from error
        _require(not address.is_loopback and not address.is_unspecified, "EKS ALB target IP is not routable")
        state = ((item.get("TargetHealth") or {}).get("State")) if isinstance(item, dict) else None
        _require(isinstance(state, str) and state, "EKS ALB target health state is missing")
        states.append(state)
    healthy = sum(state == "healthy" for state in states)
    _require(healthy > 0, "EKS ALB target group has no healthy Pod target")
    return {
        "targetGroupArn": target_group_arn,
        "targetType": "ip",
        "targetCount": len(states),
        "healthyTargetCount": healthy,
        "unhealthyTargetCount": len(states) - healthy,
        "states": {state: states.count(state) for state in sorted(set(states))},
    }


def build_kubectl_commands(
    *,
    cluster_name: str,
    region: str,
    namespace: str,
    deployment: str,
) -> list[str]:
    """Build read-only SSM commands for the EKS evidence snapshot."""

    for label, value in (
        ("cluster name", cluster_name),
        ("namespace", namespace),
        ("deployment", deployment),
    ):
        _validate_name(value, label)
    _require(isinstance(region, str) and re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z0-9-]+-\d", region), "AWS region is invalid")
    return [
        "set -euo pipefail",
        f"aws eks update-kubeconfig --name {cluster_name} --region {region} --alias scr53-eks",
        f"printf '%s\\n' __SCRUM53_HPA_BEGIN__; kubectl --context scr53-eks --namespace {namespace} get hpa {deployment} -o json; printf '%s\\n' __SCRUM53_HPA_END__",
        f"printf '%s\\n' __SCRUM53_DEPLOYMENT_BEGIN__; kubectl --context scr53-eks --namespace {namespace} get deployment {deployment} -o json; printf '%s\\n' __SCRUM53_DEPLOYMENT_END__",
        f"printf '%s\\n' __SCRUM53_PODS_BEGIN__; kubectl --context scr53-eks --namespace {namespace} get pods -l app.kubernetes.io/name=travel-planner-backend -o json; printf '%s\\n' __SCRUM53_PODS_END__",
        "printf '%s\\n' __SCRUM53_NODES_BEGIN__; kubectl --context scr53-eks get nodes -o json; printf '%s\\n' __SCRUM53_NODES_END__",
        "printf '%s\\n' __SCRUM53_EVENTS_BEGIN__; kubectl --context scr53-eks get events --all-namespaces --sort-by=.lastTimestamp -o json; printf '%s\\n' __SCRUM53_EVENTS_END__",
    ]


def _items(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = snapshot.get(key)
    return value if isinstance(value, list) else []


def build_evidence(
    *,
    node_group: dict[str, Any],
    target_health: dict[str, Any],
    hpa: dict[str, Any],
    deployment: dict[str, Any],
    pods: dict[str, Any],
    nodes: dict[str, Any],
    events: dict[str, Any],
    asg_activities: dict[str, Any],
) -> dict[str, Any]:
    """Reduce kubectl/AWS responses to comparison dimensions only."""

    hpa_status = hpa.get("status") if isinstance(hpa.get("status"), dict) else {}
    deployment_status = deployment.get("status") if isinstance(deployment.get("status"), dict) else {}
    pod_items = _items(pods, "items")
    node_items = _items(nodes, "items")
    event_items = _items(events, "items")
    activities = asg_activities.get("Activities") if isinstance(asg_activities, dict) else []
    activities = activities if isinstance(activities, list) else []
    placement = []
    for item in pod_items:
        metadata = item.get("metadata") if isinstance(item, dict) else {}
        spec = item.get("spec") if isinstance(item, dict) else {}
        status = item.get("status") if isinstance(item, dict) else {}
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            continue
        placement.append({
            "podName": metadata.get("name"),
            "nodeName": spec.get("nodeName"),
            "phase": status.get("phase") if isinstance(status, dict) else None,
        })
    return {
        "platform": "eks",
        "clusterName": node_group.get("clusterName"),
        "nodeGroupName": node_group.get("nodeGroupName"),
        "nodeGroupScalingConfig": node_group.get("scalingConfig"),
        "backingAutoScalingGroupName": node_group.get("autoScalingGroupName"),
        "hpa": {
            "desiredReplicas": hpa_status.get("desiredReplicas"),
            "currentReplicas": hpa_status.get("currentReplicas"),
            "availableReplicas": hpa_status.get("currentReplicas"),
            "conditions": [
                {"type": item.get("type"), "status": item.get("status"), "reason": item.get("reason")}
                for item in (hpa_status.get("conditions") or [])
                if isinstance(item, dict)
            ],
        },
        "deployment": {
            "desiredReplicas": deployment_status.get("replicas"),
            "updatedReplicas": deployment_status.get("updatedReplicas"),
            "availableReplicas": deployment_status.get("availableReplicas"),
            "readyReplicas": deployment_status.get("readyReplicas"),
        },
        "backendPods": {
            "count": len(pod_items),
            "placement": placement,
        },
        "nodeCount": len(node_items),
        "nodeReadyCount": sum(
            1
            for node in node_items
            if any(
                isinstance(condition, dict)
                and condition.get("type") == "Ready"
                and condition.get("status") == "True"
                for condition in (node.get("status", {}).get("conditions", []) if isinstance(node, dict) else [])
            )
        ),
        "eventCount": len(event_items),
        "nodeGroupScalingActivities": [
            {
                "statusCode": item.get("StatusCode"),
                "cause": str(item.get("Cause", ""))[:240],
                "startTime": item.get("StartTime"),
                "endTime": item.get("EndTime"),
            }
            for item in activities[:20]
            if isinstance(item, dict)
        ],
        "alb": target_health,
        "sanitization": {
            "rawKubectlOutputStored": False,
            "privateIpAndSecretFieldsDropped": True,
        },
    }


def sanitize_invocation(invocation: dict[str, Any]) -> dict[str, Any]:
    """Return safe SSM command metadata without persisting command output."""

    stdout = invocation.get("StandardOutputContent", "")
    stderr = invocation.get("StandardErrorContent", "")
    return {
        "status": invocation.get("Status"),
        "statusDetails": invocation.get("StatusDetails"),
        "responseCode": invocation.get("ResponseCode"),
        "stdoutSha256": hashlib.sha256(str(stdout).encode()).hexdigest(),
        "stderrSha256": hashlib.sha256(str(stderr).encode()).hexdigest(),
        "rawOutputStored": False,
    }


def parse_kubectl_sections(stdout: str) -> dict[str, dict[str, Any]]:
    """Parse the marker-delimited JSON emitted by ``build_kubectl_commands``."""

    snapshots: dict[str, dict[str, Any]] = {}
    for key in ("hpa", "deployment", "pods", "nodes", "events"):
        begin = f"__SCRUM53_{key.upper()}_BEGIN__"
        end = f"__SCRUM53_{key.upper()}_END__"
        match = re.search(re.escape(begin) + r"\s*(.*?)\s*" + re.escape(end), stdout, re.DOTALL)
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise EKSAdapterError(f"SSM kubectl section {key} is not JSON") from error
        if isinstance(payload, dict):
            snapshots[key] = payload
    return snapshots


def _command(args: argparse.Namespace) -> int:
    if args.action == "validate":
        node_group = resolve_node_group(
            _load_json(args.node_group_json),
            expected_cluster=args.cluster_name,
            expected_node_group=args.node_group_name,
        )
        target = validate_alb_target_health(_load_json(args.target_health_json), target_group_arn=args.target_group_arn)
        print(json.dumps({"nodeGroup": node_group, "alb": target}, indent=2, sort_keys=True))
        return 0
    if args.action == "commands":
        print(json.dumps({"commands": build_kubectl_commands(
            cluster_name=args.cluster_name,
            region=args.region,
            namespace=args.namespace,
            deployment=args.deployment,
        )}, indent=2))
        return 0
    if args.action == "sanitize-invocation":
        print(json.dumps(sanitize_invocation(_load_json(args.invocation_json)), indent=2, sort_keys=True))
        return 0
    if args.action == "build-evidence":
        invocation = _load_json(args.invocation_json)
        sections = parse_kubectl_sections(str(invocation.get("StandardOutputContent", "")))
        node_group = _load_json(args.node_group_summary_json)
        target_health = _load_json(args.alb_summary_json)
        asg_activities = _load_json(args.asg_activities_json)
        print(json.dumps(build_evidence(
            node_group=node_group,
            target_health=target_health,
            hpa=sections.get("hpa", {}),
            deployment=sections.get("deployment", {}),
            pods=sections.get("pods", {}),
            nodes=sections.get("nodes", {}),
            events=sections.get("events", {}),
            asg_activities=asg_activities,
        ), indent=2, sort_keys=True))
        return 0
    raise EKSAdapterError(f"unsupported action: {args.action}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "commands", "sanitize-invocation", "build-evidence"))
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--node-group-name")
    parser.add_argument("--target-group-arn")
    parser.add_argument("--node-group-json")
    parser.add_argument("--target-health-json")
    parser.add_argument("--region")
    parser.add_argument("--namespace")
    parser.add_argument("--deployment")
    parser.add_argument("--invocation-json")
    parser.add_argument("--node-group-summary-json")
    parser.add_argument("--alb-summary-json")
    parser.add_argument("--asg-activities-json")
    args = parser.parse_args()
    if args.action == "validate" and not all((args.node_group_name, args.target_group_arn, args.node_group_json, args.target_health_json)):
        parser.error("validate requires --node-group-name, --target-group-arn, --node-group-json and --target-health-json")
    if args.action == "commands" and not all((args.region, args.namespace, args.deployment)):
        parser.error("commands requires --region, --namespace and --deployment")
    if args.action == "sanitize-invocation" and not args.invocation_json:
        parser.error("sanitize-invocation requires --invocation-json")
    if args.action == "build-evidence" and not all((args.invocation_json, args.node_group_summary_json, args.alb_summary_json, args.asg_activities_json)):
        parser.error("build-evidence requires invocation, node-group, ALB and ASG JSON inputs")
    try:
        return _command(args)
    except EKSAdapterError as error:
        parser.exit(1, f"EKS target validation failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
