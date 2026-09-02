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
    allow_current_desired: bool = False,
) -> dict[str, Any]:
    """Validate and reduce ``eks describe-nodegroup`` to safe dimensions.

    A fresh target must still be the canonical 2/2/4 envelope.  Recovery is
    entered after the stress terminal, however, so Cluster Autoscaler may
    legitimately leave the managed node group at desired 3 or 4 while the
    recovery observer records scale-in.  That path may relax only the desired
    value; the 2/4 bounds and ACTIVE node group identity remain mandatory.
    """

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
    if allow_current_desired:
        _require(
            shape.get("min") == 2 and shape.get("max") == 4,
            f"EKS recovery node group bounds must be 2/4, got {shape}",
        )
        _require(
            isinstance(shape.get("desired"), int)
            and not isinstance(shape.get("desired"), bool)
            and 2 <= shape["desired"] <= 4,
            f"EKS recovery node group desired must be within 2..4, got {shape}",
        )
    else:
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
    allow_no_healthy: bool = False,
) -> dict[str, Any]:
    """Validate an ALB IP target group without treating Pod IPs as EC2 IDs.

    Target verification remains fail-closed by default. The live capacity
    observer may explicitly allow an all-unhealthy response so the run can
    classify it as ``ALB_SATURATION`` rather than losing the final snapshot.
    """

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
    if not allow_no_healthy:
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
        # AWS-RunShellScript executes as root with HOME unset on the EKS
        # bastion.  Pin both paths so update-kubeconfig and kubectl use the
        # same context instead of silently writing/reading different files.
        "export HOME=/root KUBECONFIG=/root/.kube/config",
        f"aws eks update-kubeconfig --name {cluster_name} --region {region} --alias scr43-eks",
        # SSM Run Command returns at most 24,000 stdout characters. Emit only
        # the fields consumed by build_evidence so a normal Deployment/Pod
        # manifest cannot hide the later node snapshot behind that cap.
        f"printf '%s\\n' __SCRUM53_HPA_BEGIN__; kubectl --context scr43-eks --namespace {namespace} get hpa {deployment} -o json | jq -c '{{spec:{{minReplicas:.spec.minReplicas,maxReplicas:.spec.maxReplicas}},status:{{desiredReplicas:.status.desiredReplicas,currentReplicas:.status.currentReplicas,conditions:(.status.conditions // [])}}}}'; printf '%s\\n' __SCRUM53_HPA_END__",
        f"printf '%s\\n' __SCRUM53_DEPLOYMENT_BEGIN__; kubectl --context scr43-eks --namespace {namespace} get deployment {deployment} -o json | jq -c '{{metadata:{{uid:.metadata.uid,creationTimestamp:.metadata.creationTimestamp,generation:.metadata.generation,deletionTimestamp:(.metadata.deletionTimestamp // null)}},spec:{{template:{{spec:{{containers:[.spec.template.spec.containers[] | {{name:.name,resources:{{requests:(.resources.requests // {{}})}}}}]}}}}}},status:{{replicas:.status.replicas,updatedReplicas:.status.updatedReplicas,availableReplicas:.status.availableReplicas,readyReplicas:.status.readyReplicas,unavailableReplicas:.status.unavailableReplicas}}}}'; printf '%s\\n' __SCRUM53_DEPLOYMENT_END__",
        f"printf '%s\\n' __SCRUM53_PODS_BEGIN__; kubectl --context scr43-eks --namespace {namespace} get pods -l app.kubernetes.io/name=travel-planner-backend -o json | jq -c '{{items:[.items[] | {{metadata:{{name:.metadata.name,uid:.metadata.uid,creationTimestamp:.metadata.creationTimestamp,deletionTimestamp:(.metadata.deletionTimestamp // null)}},spec:{{nodeName:.spec.nodeName}},status:{{phase:.status.phase,reason:.status.reason,conditions:(.status.conditions // []),containerStatuses:[.status.containerStatuses[]? | {{ready,restartCount,state,lastState,imageID}}]}}}}]}}'; printf '%s\\n' __SCRUM53_PODS_END__",
        "printf '%s\\n' __SCRUM53_NODES_BEGIN__; kubectl --context scr43-eks get nodes -o json | jq -c '{items:[.items[] | {metadata:{name:.metadata.name,uid:.metadata.uid,creationTimestamp:.metadata.creationTimestamp,deletionTimestamp:(.metadata.deletionTimestamp // null)},spec:{unschedulable:(.spec.unschedulable // false)},status:{allocatable:.status.allocatable,conditions:(.status.conditions // [])}}]}'; printf '%s\\n' __SCRUM53_NODES_END__",
        "printf '%s\\n' __SCRUM53_ALL_PODS_BEGIN__; kubectl --context scr43-eks get pods --all-namespaces -o json | jq -c '{items:[.items[] | {metadata:{namespace:.metadata.namespace,name:.metadata.name},spec:{nodeName:.spec.nodeName,containers:[.spec.containers[]? | {resources:{requests:(.resources.requests // {})}}]},status:{phase:.status.phase}}]}'; printf '%s\\n' __SCRUM53_ALL_PODS_END__",
        "printf '%s\\n' __SCRUM53_EVENTS_BEGIN__; kubectl --context scr43-eks get events --all-namespaces --sort-by=.lastTimestamp -o json | jq -c '{items:(.items | map(null))}'; printf '%s\\n' __SCRUM53_EVENTS_END__",
    ]


def _items(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = snapshot.get(key)
    return value if isinstance(value, list) else []


def _quantity(value: object, *, kind: str) -> float | None:
    """Parse the small subset of Kubernetes quantities needed for capacity.

    CPU is returned as millicores and memory as MiB. Unknown quantities stay
    ``None`` so a live run cannot silently turn a missing request into zero.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if kind == "pods":
        try:
            return float(raw)
        except ValueError:
            return None
    if kind == "cpu":
        if raw.endswith("m"):
            try:
                return float(raw[:-1])
            except ValueError:
                return None
        try:
            return float(raw) * 1000.0
        except ValueError:
            return None
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024}
    for suffix, multiplier in units.items():
        if raw.endswith(suffix):
            try:
                return float(raw[:-len(suffix)]) * multiplier
            except ValueError:
                return None
    try:
        return float(raw) / (1024 * 1024)
    except ValueError:
        return None


def _backend_pod_requests(deployment: dict[str, Any]) -> dict[str, float | None]:
    spec = deployment.get("spec") if isinstance(deployment.get("spec"), dict) else {}
    template = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    pod_spec = template.get("spec") if isinstance(template.get("spec"), dict) else {}
    containers = pod_spec.get("containers") if isinstance(pod_spec.get("containers"), list) else []
    cpu = 0.0
    memory = 0.0
    found_cpu = False
    found_memory = False
    for container in containers:
        if not isinstance(container, dict):
            continue
        resources = container.get("resources") if isinstance(container.get("resources"), dict) else {}
        requests = resources.get("requests") if isinstance(resources.get("requests"), dict) else {}
        cpu_value = _quantity(requests.get("cpu"), kind="cpu")
        memory_value = _quantity(requests.get("memory"), kind="memory")
        if cpu_value is not None:
            cpu += cpu_value
            found_cpu = True
        if memory_value is not None:
            memory += memory_value
            found_memory = True
    return {"cpuMilli": cpu if found_cpu else None, "memoryMi": memory if found_memory else None, "podCount": 1}


def calculate_capacity_curve(nodes: dict[str, Any], deployment: dict[str, Any]) -> dict[str, Any]:
    """Estimate backend-pod capacity for N1/N2/N4 from live node data.

    The estimate is deliberately conservative: each Ready, schedulable node's
    allocatable CPU/memory/pod slots is divided by the Deployment's summed pod
    requests, and the smallest observed per-node capacity is used to
    extrapolate a missing N4 snapshot. This is a planning aid for a disposable
    HPA override, never a proof of maximum platform capacity.
    """
    request = _backend_pod_requests(deployment)
    items = _items(nodes, "items")
    per_node: list[dict[str, Any]] = []
    for node in items:
        if not isinstance(node, dict):
            continue
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        status = node.get("status") if isinstance(node.get("status"), dict) else {}
        conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
        ready = any(isinstance(item, dict) and item.get("type") == "Ready" and item.get("status") == "True" for item in conditions)
        if not ready or bool(spec := node.get("spec", {}).get("unschedulable") if isinstance(node.get("spec"), dict) else False):
            continue
        allocatable = status.get("allocatable") if isinstance(status.get("allocatable"), dict) else {}
        pod_slots = _quantity(allocatable.get("pods"), kind="pods")
        cpu_slots = _quantity(allocatable.get("cpu"), kind="cpu")
        memory_slots = _quantity(allocatable.get("memory"), kind="memory")
        candidates: list[int] = []
        if pod_slots is not None:
            candidates.append(max(0, int(pod_slots // 1)))
        if request["cpuMilli"] and cpu_slots is not None:
            candidates.append(max(0, int(cpu_slots // request["cpuMilli"])))
        if request["memoryMi"] and memory_slots is not None:
            candidates.append(max(0, int(memory_slots // request["memoryMi"])))
        capacity = min(candidates) if candidates else None
        per_node.append({"nodeName": metadata.get("name"), "capacity": capacity, "allocatable": {
            "cpuMilli": cpu_slots, "memoryMi": memory_slots, "pods": pod_slots,
        }})
    observed = [int(item["capacity"]) for item in per_node if isinstance(item.get("capacity"), int) and item["capacity"] > 0]
    if not observed:
        return {"method": "allocatable-request-conservative", "request": request, "perNode": per_node, "N1": None, "N2": None, "N4": None, "valid": False}
    representative = min(observed)
    curve: dict[str, Any] = {
        "method": "allocatable-request-conservative",
        "request": request,
        "perNode": per_node,
        "observedReadyNodes": len(per_node),
        "N1": representative,
        "N2": representative * 2,
        "N4": representative * 4,
        "valid": True,
    }
    return curve


def build_hpa_override(capacity_curve: dict[str, Any]) -> dict[str, Any]:
    """Build a disposable N4+1 HPA patch and reject unknown capacity."""
    n4 = capacity_curve.get("N4")
    if not isinstance(n4, int) or n4 < 1:
        raise EKSAdapterError("cannot render HPA override without a valid N4 capacity")
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {
            "name": "backend",
            "namespace": "travel-planner",
            "annotations": {
                "load-test.kdt.travelplanner/scope": "run-scoped-n4-plus-one",
                "load-test.kdt.travelplanner/n4": str(n4),
            },
        },
        "spec": {"maxReplicas": n4 + 1},
    }


def render_hpa_override(path: str | Path, capacity_curve: dict[str, Any]) -> dict[str, Any]:
    """Write a minimal YAML patch without requiring PyYAML on the runner."""
    patch = build_hpa_override(capacity_curve)
    n4 = patch["metadata"]["annotations"]["load-test.kdt.travelplanner/n4"]
    Path(path).write_text(
        "apiVersion: autoscaling/v2\n"
        "kind: HorizontalPodAutoscaler\n"
        "metadata:\n"
        "  name: backend\n"
        "  namespace: travel-planner\n"
        "  annotations:\n"
        "    load-test.kdt.travelplanner/scope: run-scoped-n4-plus-one\n"
        f"    load-test.kdt.travelplanner/n4: \"{n4}\"\n"
        "spec:\n"
        f"  maxReplicas: {patch['spec']['maxReplicas']}\n",
        encoding="utf-8",
    )
    return patch


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
    all_pods: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reduce kubectl/AWS responses to comparison dimensions only."""

    hpa_status = hpa.get("status") if isinstance(hpa.get("status"), dict) else {}
    hpa_spec = hpa.get("spec") if isinstance(hpa.get("spec"), dict) else {}
    deployment_status = deployment.get("status") if isinstance(deployment.get("status"), dict) else {}
    pod_items = _items(pods, "items")
    all_pod_items = _items(all_pods or {}, "items")
    node_items = _items(nodes, "items")
    event_items = _items(events, "items")
    activities = asg_activities.get("Activities") if isinstance(asg_activities, dict) else []
    activities = activities if isinstance(activities, list) else []
    placement = []
    pending_reasons: list[str] = []
    for item in pod_items:
        metadata = item.get("metadata") if isinstance(item, dict) else {}
        spec = item.get("spec") if isinstance(item, dict) else {}
        status = item.get("status") if isinstance(item, dict) else {}
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            continue
        containers = status.get("containerStatuses", []) if isinstance(status, dict) else []
        ready_containers = sum(1 for container in containers if isinstance(container, dict) and container.get("ready") is True)
        restart_count = sum(
            int(container.get("restartCount", 0))
            for container in containers
            if isinstance(container, dict) and isinstance(container.get("restartCount", 0), int)
        )
        oom_killed = any(
            isinstance(container, dict)
            and (
                ((container.get("state") or {}).get("terminated") or {}).get("reason") == "OOMKilled"
                or ((container.get("lastState") or {}).get("terminated") or {}).get("reason") == "OOMKilled"
            )
            for container in containers
        )
        crash_loop = any(
            isinstance(container, dict)
            and ((container.get("state") or {}).get("waiting") or {}).get("reason") == "CrashLoopBackOff"
            for container in containers
        )
        ready_condition = next(
            (condition for condition in status.get("conditions", [])
             if isinstance(condition, dict) and condition.get("type") == "Ready"),
            {},
        )
        placement.append({
            "podName": metadata.get("name"),
            "uid": metadata.get("uid"),
            "creationTimestamp": metadata.get("creationTimestamp"),
            "deletionTimestamp": metadata.get("deletionTimestamp"),
            "readyTransitionAt": ready_condition.get("lastTransitionTime"),
            "nodeName": spec.get("nodeName"),
            "phase": status.get("phase") if isinstance(status, dict) else None,
            "readyContainers": ready_containers,
            "containerCount": len(containers) if isinstance(containers, list) else 0,
            "restartCount": restart_count,
            "oomKilled": oom_killed,
            "crashLoopBackOff": crash_loop,
            "imageIds": sorted({
                str(container.get("imageID"))
                for container in containers
                if isinstance(container, dict) and container.get("imageID")
            }),
            "ready": bool(containers) and ready_containers == len(containers),
        })
        if status.get("phase") == "Pending":
            reason = status.get("reason") or "Pending"
            pending_reasons.append(str(reason))
            for condition in status.get("conditions", []) if isinstance(status.get("conditions"), list) else []:
                if isinstance(condition, dict) and condition.get("reason"):
                    pending_reasons.append(str(condition["reason"]))
    ready_nodes: list[dict[str, Any]] = []
    pressure_nodes: list[str] = []
    for node in node_items:
        if not isinstance(node, dict):
            continue
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        status = node.get("status") if isinstance(node.get("status"), dict) else {}
        conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
        ready = any(isinstance(condition, dict) and condition.get("type") == "Ready" and condition.get("status") == "True" for condition in conditions)
        ready_condition = next(
            (condition for condition in conditions
             if isinstance(condition, dict) and condition.get("type") == "Ready"),
            {},
        )
        if ready:
            ready_nodes.append({
                "nodeName": metadata.get("name"),
                "uid": metadata.get("uid"),
                "creationTimestamp": metadata.get("creationTimestamp"),
                "deletionTimestamp": metadata.get("deletionTimestamp"),
                "readyTransitionAt": ready_condition.get("lastTransitionTime"),
                "ready": True,
            })
        pressure = [
            condition.get("type")
            for condition in conditions
            if isinstance(condition, dict) and condition.get("type") in {"MemoryPressure", "DiskPressure", "PIDPressure"} and condition.get("status") == "True"
        ]
        if pressure:
            pressure_nodes.append(str(metadata.get("name") or "unknown"))
    capacity_curve = calculate_capacity_curve(nodes, deployment)
    requested_by_node: dict[str, dict[str, float]] = {}
    for item in all_pod_items:
        if not isinstance(item, dict):
            continue
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        if status.get("phase") in {"Succeeded", "Failed"}:
            continue
        spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
        node_name = spec.get("nodeName")
        if not node_name:
            continue
        deployment_shape = {"spec": {"template": {"spec": {"containers": spec.get("containers", [])}}}}
        request = _backend_pod_requests(deployment_shape)
        row = requested_by_node.setdefault(str(node_name), {"cpuMilli": 0.0, "memoryMi": 0.0, "podCount": 0})
        row["podCount"] += 1
        if request["cpuMilli"] is not None:
            row["cpuMilli"] += float(request["cpuMilli"])
        if request["memoryMi"] is not None:
            row["memoryMi"] += float(request["memoryMi"])
    node_group_max = (node_group.get("scalingConfig") or {}).get("max")
    node_max_pending = bool(pending_reasons) and isinstance(node_group_max, int) and len(ready_nodes) >= node_group_max
    failed_activity = any(
        isinstance(item, dict)
        and str(item.get("StatusCode", "")).lower() in {"failed", "cancelled", "cancelledbyuser", "rollback"}
        for item in activities
    )
    return {
        "platform": "eks",
        "clusterName": node_group.get("clusterName"),
        "nodeGroupName": node_group.get("nodeGroupName"),
        "nodeGroupScalingConfig": node_group.get("scalingConfig"),
        "backingAutoScalingGroupName": node_group.get("autoScalingGroupName"),
        "hpa": {
            "minReplicas": hpa_spec.get("minReplicas"),
            "maxReplicas": hpa_spec.get("maxReplicas"),
            "desiredReplicas": hpa_status.get("desiredReplicas"),
            "currentReplicas": hpa_status.get("currentReplicas"),
            "availableReplicas": deployment_status.get("availableReplicas"),
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
            "unavailableReplicas": deployment_status.get("unavailableReplicas"),
        },
        "backendPods": {
            "count": len(pod_items),
            "placement": placement,
            "readyCount": sum(1 for item in placement if item.get("ready")),
            "pendingCount": sum(1 for item in placement if item.get("phase") == "Pending"),
            "pendingReasons": sorted(set(pending_reasons)),
            "restartCount": sum(int(item.get("restartCount", 0)) for item in placement),
            "imageIds": sorted({image_id for item in placement for image_id in item.get("imageIds", [])}),
        },
        "nodeCount": len(node_items),
        "nodeReadyCount": len(ready_nodes),
        "readyNodes": ready_nodes,
        "nodePressureNodes": pressure_nodes,
        "nodeSchedulingPressure": bool(pressure_nodes),
        "nodeComputeSaturated": bool(pressure_nodes),
        "nodeScaleFailed": failed_activity and len(ready_nodes) < (node_group_max if isinstance(node_group_max, int) else len(ready_nodes)),
        "nodeMaxPending": node_max_pending,
        "maxCapacityReached": bool(node_max_pending),
        "capacityCurve": capacity_curve,
        "requestedByNode": requested_by_node,
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


def high_watermark(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Keep monotonic observations when a Kubernetes phase is skipped.

    A skipped phase is recorded as ``not_observed`` by the coordinator rather
    than being treated as a missing/failed terminal state. This helper keeps
    the largest observed replica and readiness counts for later evidence.
    """

    previous = previous or {}
    result = dict(previous)
    for key in ("nodeCount", "nodeReadyCount", "eventCount"):
        if isinstance(current.get(key), int):
            result[key] = max(int(previous.get(key, 0)), current[key])
    previous_pods = previous.get("backendPods", {}) if isinstance(previous.get("backendPods"), dict) else {}
    current_pods = current.get("backendPods", {}) if isinstance(current.get("backendPods"), dict) else {}
    result["backendPods"] = {
        **previous_pods,
        **current_pods,
        "count": max(int(previous_pods.get("count", 0)), int(current_pods.get("count", 0))),
        "readyCount": max(int(previous_pods.get("readyCount", 0)), int(current_pods.get("readyCount", 0))),
        "pendingCount": max(int(previous_pods.get("pendingCount", 0)), int(current_pods.get("pendingCount", 0))),
        "pendingReasons": sorted(set(previous_pods.get("pendingReasons", [])) | set(current_pods.get("pendingReasons", []))),
    }
    previous_curve = previous.get("capacityCurve") if isinstance(previous.get("capacityCurve"), dict) else {}
    current_curve = current.get("capacityCurve") if isinstance(current.get("capacityCurve"), dict) else {}
    result["capacityCurve"] = {
        **previous_curve,
        **current_curve,
        **{key: max(int(previous_curve[key]), int(current_curve[key])) for key in ("N1", "N2", "N4")
           if isinstance(previous_curve.get(key), int) and isinstance(current_curve.get(key), int)},
    }
    result["nodeMaxPending"] = bool(previous.get("nodeMaxPending")) or bool(current.get("nodeMaxPending"))
    result["maxCapacityReached"] = bool(previous.get("maxCapacityReached")) or bool(current.get("maxCapacityReached"))
    return result


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
    for key in ("hpa", "deployment", "pods", "all_pods", "nodes", "events"):
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


def _parse_marked_json(stdout: str, begin: str, end: str, label: str) -> dict[str, Any]:
    """Parse one marker-delimited object without retaining raw SSM output."""

    match = re.search(re.escape(begin) + r"\s*(.*?)\s*" + re.escape(end), stdout, re.DOTALL)
    if not match:
        raise EKSAdapterError(f"SSM {label} section is missing")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise EKSAdapterError(f"SSM {label} section is not JSON") from error
    _require(isinstance(payload, dict), f"SSM {label} section must be an object")
    return payload


def sanitize_hpa_apply_invocation(
    invocation: dict[str, Any],
    *,
    expected_max_replicas: int,
    override_sha256: str,
) -> dict[str, Any]:
    """Validate a run-scoped HPA apply receipt and return only safe fields."""

    _require(isinstance(expected_max_replicas, int) and expected_max_replicas >= 5, "HPA max must be at least N4+1")
    _require(bool(re.fullmatch(r"[0-9a-f]{64}", str(override_sha256))), "HPA override SHA-256 is invalid")
    stdout = str(invocation.get("StandardOutputContent", ""))
    hpa = _parse_marked_json(
        stdout,
        "__SCRUM80_HPA_APPLY_BEGIN__",
        "__SCRUM80_HPA_APPLY_END__",
        "HPA apply",
    )
    metadata = hpa.get("metadata") if isinstance(hpa.get("metadata"), dict) else {}
    spec = hpa.get("spec") if isinstance(hpa.get("spec"), dict) else {}
    _require(metadata.get("name") == "backend", "HPA apply receipt targets an unexpected object")
    _require(metadata.get("namespace") == "travel-planner", "HPA apply receipt targets an unexpected namespace")
    _require(spec.get("minReplicas") == 2, "run-scoped HPA must preserve minReplicas=2")
    _require(spec.get("maxReplicas") == expected_max_replicas, "run-scoped HPA max does not match the rendered override")
    annotations = metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
    _require(annotations.get("load-test.kdt.travelplanner/scope") == "run-scoped-n4-plus-one", "HPA scope annotation is missing")
    return {
        "schemaVersion": "scrum80-hpa-receipt/v1",
        "status": invocation.get("Status"),
        "responseCode": invocation.get("ResponseCode"),
        "overrideSha256": override_sha256,
        "minReplicas": spec.get("minReplicas"),
        "maxReplicas": spec.get("maxReplicas"),
        "n4": annotations.get("load-test.kdt.travelplanner/n4"),
        "object": {"name": metadata.get("name"), "namespace": metadata.get("namespace")},
        "stdoutSha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderrSha256": hashlib.sha256(str(invocation.get("StandardErrorContent", "")).encode()).hexdigest(),
        "rawOutputStored": False,
    }


def _command(args: argparse.Namespace) -> int:
    if args.action == "validate":
        node_group = resolve_node_group(
            _load_json(args.node_group_json),
            expected_cluster=args.cluster_name,
            expected_node_group=args.node_group_name,
            allow_current_desired=args.allow_current_desired,
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
    if args.action == "sanitize-hpa-apply":
        print(json.dumps(sanitize_hpa_apply_invocation(
            _load_json(args.invocation_json),
            expected_max_replicas=args.expected_max_replicas,
            override_sha256=args.override_sha256,
        ), indent=2, sort_keys=True))
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
            all_pods=sections.get("all_pods", {}),
        ), indent=2, sort_keys=True))
        return 0
    if args.action == "capacity-curve":
        nodes = _load_json(args.nodes_json)
        deployment = _load_json(args.deployment_json)
        print(json.dumps(calculate_capacity_curve(nodes, deployment), indent=2, sort_keys=True))
        return 0
    if args.action == "render-hpa-override":
        curve = _load_json(args.capacity_curve_json)
        render_hpa_override(args.output, curve)
        print(json.dumps(build_hpa_override(curve), indent=2, sort_keys=True))
        return 0
    raise EKSAdapterError(f"unsupported action: {args.action}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "commands", "sanitize-invocation", "sanitize-hpa-apply", "build-evidence", "capacity-curve", "render-hpa-override"))
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
    parser.add_argument("--nodes-json")
    parser.add_argument("--deployment-json")
    parser.add_argument("--capacity-curve-json")
    parser.add_argument("--output")
    parser.add_argument(
        "--allow-current-desired",
        action="store_true",
        help="Recovery-only: accept desired 2..4 while retaining min=2/max=4",
    )
    parser.add_argument("--expected-max-replicas", type=int)
    parser.add_argument("--override-sha256")
    args = parser.parse_args()
    if args.action == "validate" and not all((args.node_group_name, args.target_group_arn, args.node_group_json, args.target_health_json)):
        parser.error("validate requires --node-group-name, --target-group-arn, --node-group-json and --target-health-json")
    if args.action == "commands" and not all((args.region, args.namespace, args.deployment)):
        parser.error("commands requires --region, --namespace and --deployment")
    if args.action == "sanitize-invocation" and not args.invocation_json:
        parser.error("sanitize-invocation requires --invocation-json")
    if args.action == "sanitize-hpa-apply" and not all((args.invocation_json, args.expected_max_replicas, args.override_sha256)):
        parser.error("sanitize-hpa-apply requires --invocation-json, --expected-max-replicas and --override-sha256")
    if args.action == "build-evidence" and not all((args.invocation_json, args.node_group_summary_json, args.alb_summary_json, args.asg_activities_json)):
        parser.error("build-evidence requires invocation, node-group, ALB and ASG JSON inputs")
    if args.action == "capacity-curve" and not all((args.nodes_json, args.deployment_json)):
        parser.error("capacity-curve requires --nodes-json and --deployment-json")
    if args.action == "render-hpa-override" and not all((args.capacity_curve_json, args.output)):
        parser.error("render-hpa-override requires --capacity-curve-json and --output")
    try:
        return _command(args)
    except EKSAdapterError as error:
        parser.exit(1, f"EKS target validation failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
