#!/usr/bin/env python3
"""Read-only observer for the AWS Capacity/Scale Stress campaigns.

The observer samples capacity, platform readiness, Runner statistics and
CloudWatch data-tier/T3 signals into the coordinator's sanitized JSONL file.
Its AWS port allows only describe/get operations; it never changes a desired
capacity, image, rollout or Kubernetes object.  ``--once`` makes the same
collector usable in offline contract tests and a normal invocation polls
until interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


READ_OPERATIONS = {
    "describe-auto-scaling-groups",
    "describe-scaling-activities",
    "describe-nodegroup",
    "describe-instances",
    "describe-target-health",
    "get-metric-statistics",
}

# SSM Run Command is used only with the adapter's marker-delimited read-only
# kubectl command. Keep these operations out of READ_OPERATIONS so the normal
# AWS observation port still rejects every desired-capacity/scale mutation.
SSM_OBSERVATION_OPERATIONS = {"send-command", "get-command-invocation"}


class ObserverError(RuntimeError):
    """A sanitized observer failure."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def metadata_timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def duration_seconds(value: object) -> float | None:
    """Parse the profile's whole-unit stage duration without guessing."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh])", value.strip())
    if not match:
        return None
    amount = float(match.group(1))
    multiplier = {"s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]
    return amount * multiplier


def stage_fields(metadata: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Resolve the fixed stress stage from run metadata and wall-clock time.

    Stage labels are derived from the immutable k6 metadata written at run
    start. This adds no control or AWS mutation; it only makes observer
    snapshots joinable to the preregistered 1x/2x/4x/8x schedule.
    """
    inputs = metadata.get("effectiveInputs") if isinstance(metadata.get("effectiveInputs"), Mapping) else {}
    multipliers = inputs.get("stageMultipliers")
    durations = inputs.get("stageDurations")
    started = metadata_timestamp(metadata.get("startedAtUtc"))
    if not isinstance(multipliers, list) or not isinstance(durations, list) or len(multipliers) != len(durations) or started is None:
        return {}
    parsed = [duration_seconds(value) for value in durations]
    if any(value is None for value in parsed):
        return {}
    elapsed = max(0.0, now.timestamp() - started)
    cursor = 0.0
    selected = len(multipliers) - 1
    for index, duration in enumerate(parsed):
        assert duration is not None
        if elapsed < cursor + duration:
            selected = index
            break
        cursor += duration
    base_rate = inputs.get("baseRate")
    try:
        target_rate = float(base_rate) * float(multipliers[selected])
    except (TypeError, ValueError, IndexError):
        target_rate = None
    return {
        "stageIndex": selected,
        "stageMultiplier": multipliers[selected],
        "targetRate": target_rate,
        "stageElapsedSeconds": round(elapsed, 3),
    }


class AwsReadOnly:
    def __init__(self, *, region: str, profile: str | None = None) -> None:
        self.region = region
        self.profile = profile

    def _call(self, service: str, operation: str, arguments: Sequence[str]) -> dict[str, Any]:
        command = ["aws", service, operation, *arguments, "--region", self.region, "--output", "json"]
        if self.profile:
            command += ["--profile", self.profile]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise ObserverError(f"AWS observation failed for {service}:{operation}")
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as error:
            raise ObserverError(f"AWS observation returned invalid JSON for {service}:{operation}") from error
        if not isinstance(payload, dict):
            raise ObserverError(f"AWS observation returned a non-object for {service}:{operation}")
        return payload

    def call(self, service: str, operation: str, arguments: Sequence[str]) -> dict[str, Any]:
        if operation not in READ_OPERATIONS:
            raise ObserverError(f"observer refused non-read operation: {operation}")
        return self._call(service, operation, arguments)

    def call_targeted_ssm(self, operation: str, arguments: Sequence[str]) -> dict[str, Any]:
        if operation not in SSM_OBSERVATION_OPERATIONS:
            raise ObserverError(f"observer refused non-observation SSM operation: {operation}")
        return self._call("ssm", operation, arguments)


def read_optional(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ObserverError(f"observer fixture is not valid JSON: {path.name}") from error
    return value if isinstance(value, dict) else {}


def last_jsonl(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _optional_bool(payload: Mapping[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _first_transition(previous: Mapping[str, Any], current: Mapping[str, Any], key: str, now: str) -> str | None:
    """Return a transition timestamp only when a state changed from false."""
    if current.get(key) is True and previous.get(key) is not True:
        return now
    previous_value = previous.get(f"{key}At")
    return previous_value if isinstance(previous_value, str) else None


def required_eks_observations(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Classify the EKS evidence dimensions without coercing missing data."""
    required = {
        "hpa": isinstance(evidence.get("hpa"), Mapping),
        "deployment": isinstance(evidence.get("deployment"), Mapping),
        "backendPods": isinstance(evidence.get("backendPods"), Mapping),
        "nodes": isinstance(evidence.get("nodeCount"), int) and isinstance(evidence.get("nodeReadyCount"), int),
        "pendingReasons": isinstance((evidence.get("backendPods") or {}).get("pendingReasons"), list) if isinstance(evidence.get("backendPods"), Mapping) else False,
        "alb": isinstance(evidence.get("alb"), Mapping),
    }
    return {"status": "complete" if all(required.values()) else "missing", "required": required}


def ec2_capacity(payload: Mapping[str, Any]) -> tuple[int, bool, dict[str, Any]]:
    groups = payload.get("AutoScalingGroups")
    if not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], Mapping):
        raise ObserverError("EC2 observer could not resolve exactly one ASG")
    group = groups[0]
    try:
        desired = int(group.get("DesiredCapacity"))
        minimum = int(group.get("MinSize"))
        maximum = int(group.get("MaxSize"))
    except (TypeError, ValueError) as error:
        raise ObserverError("EC2 ASG capacity fields are invalid") from error
    members = group.get("Instances") if isinstance(group.get("Instances"), list) else []
    healthy = sum(1 for member in members if isinstance(member, Mapping) and member.get("LifecycleState") == "InService" and member.get("HealthStatus") == "Healthy")
    return desired, healthy >= desired and desired >= minimum, {"min": minimum, "desired": desired, "max": maximum, "healthyMembers": healthy}


def eks_capacity(payload: Mapping[str, Any]) -> tuple[int, bool, dict[str, Any]]:
    node = payload.get("nodegroup") if isinstance(payload.get("nodegroup"), Mapping) else {}
    scaling = node.get("scalingConfig") if isinstance(node.get("scalingConfig"), Mapping) else {}
    try:
        desired = int(scaling.get("desiredSize"))
        minimum = int(scaling.get("minSize"))
        maximum = int(scaling.get("maxSize"))
    except (TypeError, ValueError) as error:
        raise ObserverError("EKS node-group scaling fields are invalid") from error
    return desired, node.get("status") == "ACTIVE" and desired >= minimum, {"min": minimum, "desired": desired, "max": maximum, "status": node.get("status")}


def cloudwatch_metric(aws: AwsReadOnly, namespace: str, metric: str, statistic: str, dimensions: Mapping[str, str] | None, now: datetime) -> float | None:
    args = ["--namespace", namespace, "--metric-name", metric, "--statistics", statistic, "--period", "60", "--start-time", iso(now - timedelta(minutes=5)), "--end-time", iso(now)]
    if dimensions:
        args += ["--dimensions", *[f"Name={key},Value={value}" for key, value in dimensions.items()]]
    payload = aws.call("cloudwatch", "get-metric-statistics", args)
    points = payload.get("Datapoints") if isinstance(payload.get("Datapoints"), list) else []
    values = [float(item.get(statistic)) for item in points if isinstance(item, Mapping) and isinstance(item.get(statistic), (int, float))]
    return max(values) if values else None


def best_effort_cloudwatch_metric(
    aws: AwsReadOnly,
    namespace: str,
    metric: str,
    statistic: str,
    dimensions: Mapping[str, str] | None,
    now: datetime,
    observation_errors: list[str],
) -> float | None:
    """Keep the capacity window alive when Runner IAM cannot read CloudWatch.

    ASG/EKS capacity and Runner stats are still useful read-only observations,
    while a permission-denied CloudWatch call must be recorded as a limitation
    rather than terminating the workload or being mistaken for a zero metric.
    The error string is intentionally sanitized and contains no AWS response.
    """
    try:
        return cloudwatch_metric(aws, namespace, metric, statistic, dimensions, now)
    except ObserverError:
        observation_errors.append(f"{namespace}:{metric}:read-failed")
        return None


def refresh_eks_evidence(args: argparse.Namespace, aws: AwsReadOnly) -> dict[str, Any]:
    """Refresh sanitized EKS state through the private SSM bastion.

    The initial target snapshot is intentionally not reused here. Each poll
    sends the adapter's fixed read-only kubectl command to the bastion, joins
    it with fresh node-group/ALB observations, and atomically replaces the
    sanitized evidence file. A failed refresh raises so the caller records an
    invalid observation instead of turning stale data into scale-out proof.
    """
    if not args.eks_bastion_id or not args.target_group_arn:
        raise ObserverError("live EKS refresh requires --eks-bastion-id and --target-group-arn")
    try:
        from eks_target_adapter import (
            EKSAdapterError,
            build_evidence,
            build_kubectl_commands,
            parse_kubectl_sections,
            resolve_node_group,
            sanitize_invocation,
            validate_alb_target_health,
        )
    except ImportError:
        # The observer is also loaded directly by the repository's unit tests,
        # where Python does not necessarily put this script's directory on
        # sys.path. Load the sibling adapter without widening the import path.
        import importlib.util

        adapter_path = Path(__file__).with_name("eks_target_adapter.py")
        spec = importlib.util.spec_from_file_location("scrum80_eks_target_adapter", adapter_path)
        if spec is None or spec.loader is None:
            raise ObserverError("EKS observer adapter is unavailable")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        build_evidence = adapter.build_evidence
        EKSAdapterError = adapter.EKSAdapterError
        build_kubectl_commands = adapter.build_kubectl_commands
        parse_kubectl_sections = adapter.parse_kubectl_sections
        resolve_node_group = adapter.resolve_node_group
        sanitize_invocation = adapter.sanitize_invocation
        validate_alb_target_health = adapter.validate_alb_target_health

    nodegroup_payload = aws.call(
        "eks",
        "describe-nodegroup",
        ["--cluster-name", args.cluster_name, "--nodegroup-name", args.node_group_name],
    )
    try:
        node_group = resolve_node_group(
            nodegroup_payload,
            expected_cluster=args.cluster_name,
            expected_node_group=args.node_group_name,
        )
        target_payload = aws.call("elbv2", "describe-target-health", ["--target-group-arn", args.target_group_arn])
        target_health = validate_alb_target_health(
            target_payload,
            target_group_arn=args.target_group_arn,
            allow_no_healthy=True,
        )
    except EKSAdapterError as error:
        raise ObserverError("EKS target evidence failed adapter validation") from error
    activities = aws.call(
        "autoscaling",
        "describe-scaling-activities",
        ["--auto-scaling-group-name", node_group["autoScalingGroupName"], "--max-items", "20"],
    )
    try:
        commands = build_kubectl_commands(
            cluster_name=args.cluster_name,
            region=args.region,
            namespace=args.namespace,
            deployment=args.deployment,
        )
    except EKSAdapterError as error:
        raise ObserverError("EKS kubectl evidence command validation failed") from error
    parameters = json.dumps({"commands": commands}, separators=(",", ":"))
    command_payload = aws.call_targeted_ssm(
        "send-command",
        [
            "--instance-ids", args.eks_bastion_id,
            "--document-name", "AWS-RunShellScript",
            "--comment", "SCRUM-80 live EKS observer snapshot",
            "--parameters", parameters,
        ],
    )
    command_id = ((command_payload.get("Command") or {}).get("CommandId"))
    if not isinstance(command_id, str) or not command_id:
        raise ObserverError("EKS refresh returned no SSM command id")

    invocation: dict[str, Any] = {}
    status = ""
    for _ in range(30):
        invocation = aws.call_targeted_ssm(
            "get-command-invocation",
            ["--command-id", command_id, "--instance-id", args.eks_bastion_id],
        )
        status = str(invocation.get("Status") or "")
        if status == "Success":
            break
        if status in {"Failed", "Cancelled", "TimedOut", "Undeliverable", "Terminated"}:
            raise ObserverError(f"EKS bastion refresh failed: {status}")
        time.sleep(1)
    if status != "Success":
        raise ObserverError("EKS bastion refresh timed out")

    try:
        sections = parse_kubectl_sections(str(invocation.get("StandardOutputContent", "")))
        evidence = build_evidence(
            node_group=node_group,
            target_health=target_health,
            hpa=sections.get("hpa", {}),
            deployment=sections.get("deployment", {}),
            pods=sections.get("pods", {}),
            nodes=sections.get("nodes", {}),
            events=sections.get("events", {}),
            asg_activities=activities,
            all_pods=sections.get("all_pods", {}),
        )
    except EKSAdapterError as error:
        raise ObserverError("EKS kubectl evidence parse failed") from error
    evidence["observedAtUtc"] = iso(utc_now())
    evidence["ssmInvocation"] = sanitize_invocation(invocation)
    target_path = args.eks_evidence_file
    if target_path is not None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_name(f".{target_path.name}.tmp")
        temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target_path)
    return evidence


def collect_snapshot(args: argparse.Namespace, aws: AwsReadOnly) -> dict[str, Any]:
    now = utc_now()
    fixture = read_optional(args.sample_json)
    if fixture:
        fixture["ts"] = iso(now)
        fixture.setdefault("sources", ["sample-json"])
        fixture.setdefault("observationErrors", [])
        fixture.setdefault("requiredObservationStatus", {"status": "fixture"})
        return fixture
    if args.platform == "ec2":
        capacity_payload = aws.call("autoscaling", "describe-auto-scaling-groups", ["--auto-scaling-group-names", args.asg_name])
        logical_capacity, capacity_healthy, capacity = ec2_capacity(capacity_payload)
    else:
        capacity_payload = aws.call("eks", "describe-nodegroup", ["--cluster-name", args.cluster_name, "--nodegroup-name", args.node_group_name])
        logical_capacity, capacity_healthy, capacity = eks_capacity(capacity_payload)

    runner = last_jsonl(args.runner_stats_file)
    docker = runner.get("docker") if isinstance(runner.get("docker"), Mapping) else {}
    cloudwatch: dict[str, Any] = {}
    observation_errors: list[str] = []
    if args.platform == "ec2" and args.asg_name:
        cloudwatch["backendCpuPercent"] = best_effort_cloudwatch_metric(
            aws, "AWS/EC2", "CPUUtilization", "Average", {"AutoScalingGroupName": args.asg_name}, now,
            observation_errors,
        )
    if args.rds_instance_id:
        rds_dimensions = {"DBInstanceIdentifier": args.rds_instance_id}
        for metric_name, key in (
            ("CPUUtilization", "rdsCpuPercent"),
            ("DatabaseConnections", "rdsDatabaseConnections"),
            ("FreeableMemory", "rdsFreeableMemoryBytes"),
            ("ReadLatency", "rdsReadLatencySeconds"),
            ("WriteLatency", "rdsWriteLatencySeconds"),
        ):
            cloudwatch[key] = best_effort_cloudwatch_metric(
                aws, "AWS/RDS", metric_name, "Average", rds_dimensions, now, observation_errors,
            )
    if args.redis_cluster_id:
        redis_dimensions = {"CacheClusterId": args.redis_cluster_id}
        for metric_name, key in (
            ("EngineCPUUtilization", "redisCpuPercent"),
            ("CurrConnections", "redisCurrentConnections"),
            ("DatabaseMemoryUsagePercentage", "redisMemoryPercent"),
            ("Evictions", "redisEvictions"),
            ("Reclaimed", "redisReclaimed"),
            ("CPUCreditBalance", "redisT3CreditBalance"),
            ("CPUCreditUsage", "redisT3CreditUsage"),
        ):
            cloudwatch[key] = best_effort_cloudwatch_metric(
                aws, "AWS/ElastiCache", metric_name, "Average", redis_dimensions, now, observation_errors,
            )
    alb_dimension = getattr(args, "alb_dimension", "")
    target_group_dimension = getattr(args, "target_group_dimension", "")
    if alb_dimension:
        alb_dimensions = {"LoadBalancer": alb_dimension}
        for metric_name, key in (
            ("RequestCount", "albRequestCount"),
            ("TargetResponseTime", "albTargetResponseTimeSeconds"),
            ("HealthyHostCount", "albHealthyHostCount"),
            ("HTTPCode_ELB_5XX_Count", "albElb5xx"),
            ("HTTPCode_Target_5XX_Count", "albTarget5xx"),
        ):
            cloudwatch[key] = best_effort_cloudwatch_metric(
                aws, "AWS/ApplicationELB", metric_name, "Sum" if metric_name in {"RequestCount", "HTTPCode_ELB_5XX_Count", "HTTPCode_Target_5XX_Count"} else "Average", alb_dimensions, now, observation_errors,
            )
    if target_group_dimension:
        target_dimensions = {"TargetGroup": target_group_dimension}
        cloudwatch["albTargetHealthyHostCount"] = best_effort_cloudwatch_metric(
            aws, "AWS/ApplicationELB", "HealthyHostCount", "Average", target_dimensions, now, observation_errors,
        )
    for instance_id in getattr(args, "t3_instance_ids", []) or []:
        dimensions = {"InstanceId": instance_id}
        cloudwatch.setdefault("t3CreditBalance", {})[instance_id] = best_effort_cloudwatch_metric(
            aws, "AWS/EC2", "CPUCreditBalance", "Average", dimensions, now, observation_errors,
        )
        cloudwatch.setdefault("t3CreditUsage", {})[instance_id] = best_effort_cloudwatch_metric(
            aws, "AWS/EC2", "CPUCreditUsage", "Average", dimensions, now, observation_errors,
        )

    slo = last_jsonl(args.slo_window_file)
    metadata_path = getattr(args, "metadata_file", None)
    if metadata_path is None and getattr(args, "run_dir", None) is not None:
        metadata_path = args.run_dir / "metadata.json"
    metadata = read_optional(metadata_path)
    previous_path = getattr(args, "snapshot_file", None)
    if previous_path is None and getattr(args, "run_dir", None) is not None:
        previous_path = args.run_dir / "snapshots.jsonl"
    previous = last_jsonl(previous_path)
    platform_evidence: dict[str, Any] = {}
    eks_refresh_ok = False
    if args.platform == "eks":
        try:
            # Never fall back to the previous evidence file for a live poll:
            # stale HPA/Pod/node state must invalidate scale-out proof.
            platform_evidence = refresh_eks_evidence(args, aws)
            eks_refresh_ok = True
        except ObserverError:
            observation_errors.append("eks:live-refresh-failed")
    backend_pods = platform_evidence.get("backendPods") if isinstance(platform_evidence.get("backendPods"), Mapping) else {}
    hpa_evidence = platform_evidence.get("hpa") if isinstance(platform_evidence.get("hpa"), Mapping) else {}
    deployment_evidence = platform_evidence.get("deployment") if isinstance(platform_evidence.get("deployment"), Mapping) else {}
    evidence_node_count = platform_evidence.get("nodeCount") if isinstance(platform_evidence.get("nodeCount"), int) else None
    evidence_ready_nodes = platform_evidence.get("nodeReadyCount") if isinstance(platform_evidence.get("nodeReadyCount"), int) else None
    current_pods = backend_pods.get("count") if isinstance(backend_pods.get("count"), int) else None
    current_nodes = evidence_node_count
    baseline_pods = previous.get("initialBackendPodCount") if isinstance(previous.get("initialBackendPodCount"), int) else current_pods
    baseline_nodes = previous.get("initialNodeCount") if isinstance(previous.get("initialNodeCount"), int) else current_nodes
    pod_scale_out = current_pods is not None and baseline_pods is not None and current_pods > baseline_pods
    node_scale_out = current_nodes is not None and baseline_nodes is not None and current_nodes > baseline_nodes
    if args.platform == "eks" and eks_refresh_ok:
        required_observations = required_eks_observations(platform_evidence)
    elif args.platform == "eks":
        required_observations = {"status": "missing", "required": {}, "reason": "live-refresh-not-observed"}
    else:
        required_observations = {"status": "not-applicable"}
    slo_window_present = "sloWindow" in slo
    slo_window_complete = slo.get("sloWindowComplete") if isinstance(slo.get("sloWindowComplete"), bool) else None
    explicit_data_tier_saturated = _optional_bool(slo, "dataTierSaturated")
    logical_capacity_stable = _optional_bool(slo, "logicalCapacityStable")
    scale_in_stable = _optional_bool(slo, "scaleInStable")
    node_max_pending = platform_evidence.get("nodeMaxPending") if isinstance(platform_evidence.get("nodeMaxPending"), bool) else None
    max_capacity_reached = platform_evidence.get("maxCapacityReached") if isinstance(platform_evidence.get("maxCapacityReached"), bool) else None
    if max_capacity_reached is None and isinstance(node_max_pending, bool):
        max_capacity_reached = node_max_pending and isinstance(capacity.get("max"), int) and logical_capacity >= capacity["max"]
    activities = platform_evidence.get("nodeGroupScalingActivities") if isinstance(platform_evidence.get("nodeGroupScalingActivities"), list) else []
    ca_activity_active = any(
        isinstance(activity, Mapping) and str(activity.get("statusCode", "")).lower() in {"inprogress", "pending"}
        for activity in activities
    )
    hpa_max = hpa_evidence.get("maxReplicas") if isinstance(hpa_evidence, Mapping) else None
    hpa_desired = hpa_evidence.get("desiredReplicas") if isinstance(hpa_evidence, Mapping) else None
    pending_count = backend_pods.get("pendingCount") if isinstance(backend_pods, Mapping) else None
    ready_pods = deployment_evidence.get("readyReplicas") if isinstance(deployment_evidence, Mapping) else None
    deployment_unavailable = deployment_evidence.get("unavailableReplicas") if isinstance(deployment_evidence, Mapping) else None
    restart_count = backend_pods.get("restartCount") if isinstance(backend_pods, Mapping) else None
    alb_healthy = platform_evidence.get("alb", {}).get("healthyTargetCount") if isinstance(platform_evidence.get("alb"), Mapping) else None
    alb_target_count = platform_evidence.get("alb", {}).get("targetCount") if isinstance(platform_evidence.get("alb"), Mapping) else None
    node_scale_in_progress = isinstance(capacity.get("desired"), int) and isinstance(evidence_ready_nodes, int) and capacity["desired"] > evidence_ready_nodes
    new_pod_not_ready = isinstance(hpa_desired, int) and isinstance(ready_pods, int) and hpa_desired > ready_pods
    backend_oom = any(item.get("oomKilled") is True for item in backend_pods.get("placement", []) if isinstance(item, Mapping)) if isinstance(backend_pods, Mapping) else False
    backend_unhealthy = (isinstance(deployment_unavailable, int) and deployment_unavailable > 0) or (isinstance(restart_count, int) and restart_count > 0)
    alb_saturated = isinstance(alb_healthy, int) and isinstance(alb_target_count, int) and alb_target_count > 0 and alb_healthy == 0
    data_tier_signals = {
        "rdsCpu": isinstance(cloudwatch.get("rdsCpuPercent"), (int, float)) and cloudwatch["rdsCpuPercent"] >= 100,
        "rdsNoFreeableMemory": isinstance(cloudwatch.get("rdsFreeableMemoryBytes"), (int, float)) and cloudwatch["rdsFreeableMemoryBytes"] <= 0,
        "redisCpu": isinstance(cloudwatch.get("redisCpuPercent"), (int, float)) and cloudwatch["redisCpuPercent"] >= 100,
        "redisMemory": isinstance(cloudwatch.get("redisMemoryPercent"), (int, float)) and cloudwatch["redisMemoryPercent"] >= 100,
        "redisEvictions": isinstance(cloudwatch.get("redisEvictions"), (int, float)) and cloudwatch["redisEvictions"] > 0,
        "redisCreditsDepleted": isinstance(cloudwatch.get("redisT3CreditBalance"), (int, float)) and cloudwatch["redisT3CreditBalance"] <= 0,
    }
    data_tier_saturated = explicit_data_tier_saturated is True or any(data_tier_signals.values())
    resource_pending = (
        isinstance(pending_count, (int, float)) and pending_count > 0
    ) or (
        isinstance(backend_pods, Mapping)
        and isinstance(backend_pods.get("pendingReasons"), list)
        and any(any(word in str(reason).lower() for word in ("schedul", "insufficient", "resource")) for reason in backend_pods.get("pendingReasons", []))
    )
    node_compute_saturated = bool(platform_evidence.get("nodeComputeSaturated")) or bool(platform_evidence.get("nodeSchedulingPressure"))
    node_scale_failed = bool(platform_evidence.get("nodeScaleFailed")) and (node_scale_in_progress or bool(resource_pending))
    node_maximum = capacity.get("max") if isinstance(capacity, Mapping) else None
    node_scale_not_triggered = bool(
        resource_pending
        and isinstance(node_maximum, int)
        and isinstance(evidence_ready_nodes, int)
        and evidence_ready_nodes < node_maximum
        and not ca_activity_active
        and not node_scale_in_progress
    )
    achieved_rps = slo.get("achievedRps")
    stage_info = stage_fields(metadata, now)
    target_rps = stage_info.get("targetRate") if isinstance(stage_info, Mapping) else None
    throughput_plateau = (
        isinstance(achieved_rps, (int, float))
        and isinstance(target_rps, (int, float))
        and achieved_rps < target_rps * 0.9
        and slo_window_complete is True
    )
    snapshot = {
        "ts": iso(now),
        "platform": args.platform,
        "campaignStage": (metadata.get("effectiveInputs") or {}).get("campaignStage", "capacity-stress") if isinstance(metadata.get("effectiveInputs"), Mapping) else "capacity-stress",
        "logicalCapacity": logical_capacity,
        "capacityHealthy": capacity_healthy,
        "logicalCapacityStable": logical_capacity_stable,
        "capacityAtMax": logical_capacity == capacity.get("max") if isinstance(capacity.get("max"), int) else None,
        "maxCapacityReached": max_capacity_reached,
        "caActivityActive": ca_activity_active,
        "nodeScaleInProgress": node_scale_in_progress,
        "newNodeNotReady": node_scale_in_progress,
        "newPodNotReady": new_pod_not_ready,
        "albHealthy": alb_healthy is None or alb_healthy > 0,
        "backendRestartCount": restart_count,
        "backendOom": backend_oom,
        "backendUnhealthy": backend_unhealthy,
        "albSaturated": alb_saturated,
        "nodeComputeSaturated": node_compute_saturated,
        "nodeScaleFailed": node_scale_failed,
        "albMetrics": {key: value for key, value in cloudwatch.items() if key.startswith("alb")},
        "nodeScaleNotTriggered": node_scale_not_triggered,
        "throughputPlateau": throughput_plateau,
        "runnerValid": not bool(slo.get("runnerVusExhausted")),
        "hpaCapacityExhausted": isinstance(hpa_max, int) and isinstance(hpa_desired, int) and hpa_desired >= hpa_max and (bool(pending_count) or bool(slo.get("sloBreached")) or bool(max_capacity_reached)),
        "scaleInStable": scale_in_stable,
        "capacity": capacity,
        "backendCpuPercent": slo.get("backendCpuPercent", cloudwatch.get("backendCpuPercent")),
        "runnerCpuPercent": docker.get("CPUPerc"),
        "runnerMemoryPercent": docker.get("MemPerc"),
        "rdsCpuPercent": cloudwatch.get("rdsCpuPercent"),
        "rdsDatabaseConnections": cloudwatch.get("rdsDatabaseConnections"),
        "rdsFreeableMemoryBytes": cloudwatch.get("rdsFreeableMemoryBytes"),
        "rdsReadLatencySeconds": cloudwatch.get("rdsReadLatencySeconds"),
        "rdsWriteLatencySeconds": cloudwatch.get("rdsWriteLatencySeconds"),
        "redisCpuPercent": cloudwatch.get("redisCpuPercent"),
        "redisCurrentConnections": cloudwatch.get("redisCurrentConnections"),
        "redisMemoryPercent": cloudwatch.get("redisMemoryPercent"),
        "redisEvictions": cloudwatch.get("redisEvictions"),
        "redisReclaimed": cloudwatch.get("redisReclaimed"),
        "achievedRps": achieved_rps,
        "targetRps": target_rps,
        "t3CreditBalance": cloudwatch.get("t3CreditBalance", cloudwatch.get("redisT3CreditBalance")),
        "t3CreditUsage": cloudwatch.get("t3CreditUsage", cloudwatch.get("redisT3CreditUsage")),
        "dataTierMetrics": {
            key: value for key, value in cloudwatch.items()
            if key.startswith("rds") or key.startswith("redis")
        },
        "dataTierSaturated": data_tier_saturated,
        "dataTierSaturationSignals": data_tier_signals,
        "sloWindow": slo.get("sloWindow") if slo_window_present else None,
        "sloWindowComplete": slo_window_complete,
        "sloWindowSeconds": slo.get("sloWindowSeconds"),
        "sloBreached": slo.get("sloBreached") if isinstance(slo.get("sloBreached"), bool) else None,
        "runnerVusExhausted": _optional_bool(slo, "runnerVusExhausted"),
        "backendPods": backend_pods if args.platform == "eks" else None,
        "hpa": hpa_evidence if args.platform == "eks" else None,
        "deployment": deployment_evidence if args.platform == "eks" else None,
        "pendingReasons": backend_pods.get("pendingReasons") if args.platform == "eks" else None,
        "readyNodeCount": evidence_ready_nodes if args.platform == "eks" else None,
        "nodeSchedulingPressure": platform_evidence.get("nodeSchedulingPressure") if args.platform == "eks" else None,
        "requiredObservationStatus": required_observations,
        "requiredObservationsValid": required_observations.get("status") in {"complete", "not-applicable"},
        "eksEvidenceObservedAt": platform_evidence.get("observedAtUtc") if args.platform == "eks" else None,
        "podScaleOut": pod_scale_out if current_pods is not None and baseline_pods is not None else None,
        "nodeScaleOut": node_scale_out if current_nodes is not None and baseline_nodes is not None else None,
        "podScaleOutAt": _first_transition(previous, {"podScaleOut": pod_scale_out, "podScaleOutAt": previous.get("podScaleOutAt")}, "podScaleOut", iso(now)),
        "nodeScaleOutAt": _first_transition(previous, {"nodeScaleOut": node_scale_out, "nodeScaleOutAt": previous.get("nodeScaleOutAt")}, "nodeScaleOut", iso(now)),
        "initialBackendPodCount": baseline_pods,
        "initialNodeCount": baseline_nodes,
        "observationErrors": sorted(set(observation_errors)),
        "sources": [
            "autoscaling" if args.platform == "ec2" else "eks",
            "runner-stats",
            "cloudwatch" if cloudwatch and not observation_errors else "cloudwatch-unavailable" if observation_errors else "none",
        ],
    }
    snapshot.update(stage_info)
    return snapshot


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--metadata-file", type=Path, default=None)
    parser.add_argument("--platform", choices=("ec2", "eks"), required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    parser.add_argument("--asg-name", default="")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument("--node-group-name", default="")
    parser.add_argument("--eks-bastion-id", default="")
    parser.add_argument("--target-group-arn", default="")
    parser.add_argument("--alb-dimension", default="")
    parser.add_argument("--target-group-dimension", default="")
    parser.add_argument("--namespace", default="travel-planner")
    parser.add_argument("--deployment", default="backend")
    parser.add_argument("--rds-instance-id", default="")
    parser.add_argument("--redis-cluster-id", default="")
    parser.add_argument(
        "--t3-instance-id",
        dest="t3_instance_ids",
        action="append",
        default=[],
        help="Optional EC2 InstanceId to sample CPUCreditBalance/CPUCreditUsage (repeatable).",
    )
    parser.add_argument("--runner-stats-file", type=Path, default=None)
    parser.add_argument("--slo-window-file", type=Path, default=None)
    parser.add_argument(
        "--eks-evidence-file",
        type=Path,
        default=None,
        help="Optional sanitized adapter evidence refreshed by the read-only EKS observer path.",
    )
    parser.add_argument("--sample-json", type=Path, default=None)
    parser.add_argument("--snapshot-file", type=Path, default=None)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.platform == "ec2" and not args.sample_json and not args.asg_name:
        parser.error("--asg-name is required for EC2 observation")
    if args.platform == "eks" and not args.sample_json and (not args.cluster_name or not args.node_group_name):
        parser.error("--cluster-name and --node-group-name are required for EKS observation")
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = (args.snapshot_file or run_dir / "snapshots.jsonl").resolve()
    aws = AwsReadOnly(region=args.region, profile=args.profile)
    while True:
        snapshot = collect_snapshot(args, aws)
        with snapshot_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(snapshot, sort_keys=True) + "\n")
        print(json.dumps({"ts": snapshot["ts"], "platform": snapshot.get("platform"), "logicalCapacity": snapshot.get("logicalCapacity")}, sort_keys=True), flush=True)
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ObserverError as error:
        print(f"[capacity-observer] blocked: {error}", file=sys.stderr)
        raise SystemExit(2)
