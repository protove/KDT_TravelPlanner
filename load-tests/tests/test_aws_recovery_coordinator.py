"""Contract tests for the fail-closed AWS Recovery live coordinator.

Every test injects fake AWS/SSM/mutation ports so no credentials, Docker,
or live account is required. The suite pins the safety properties the live
runs depend on: strict step order, T1 gating behind an active workload and
a verified pre-T1 window, exactly-once approved mutations, digest-bound
approvals, and dry-run producing zero mutations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


MODULE_PATH = (
    Path(__file__).parents[2] / "scripts" / "loadtest" / "aws" / "coordinate-aws-recovery.py"
)
SPEC = importlib.util.spec_from_file_location("coordinate_aws_recovery", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.current = start

    def now(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += max(seconds, 0.01)


class FakeSsm:
    """Routes coordinator SSM commands by their comment label."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.events: list[tuple[str, str]] = []
        self.comments: list[str] = []
        self.stats_queue: list[dict] = []
        self.run_end_queue: list[str] = ["present"]
        self.operator_event: dict | None = None
        self.eks_snapshot_queue: list[dict[str, dict]] = []
        self.fail_comments: set[str] = set()

    def run(self, command: str, *, timeout_seconds: int = 120, comment: str = "") -> str:
        self.comments.append(comment)
        if comment in self.fail_comments:
            raise AssertionError(f"unexpected SSM command in this phase: {comment}")
        if comment == "recovery-preflight":
            return "[recovery] preflight passed: run=test"
        if comment == "recovery-workload-start":
            return "started:4242"
        if comment == "live-stats":
            stats = self.stats_queue.pop(0) if self.stats_queue else {
                "status": "ok",
                "operations": 1200,
                "completed": 1200,
                "successful": 1200,
                "unexpectedErrors": 0,
                "contractFailures": 0,
            }
            return json.dumps(stats)
        if comment.startswith("record-"):
            event = comment.split("-", 1)[1]
            detail = command.split(" ")[-3] if event else ""
            self.events.append((event, command))
            return f"[event] {event}"
        if comment == "operator-recovery-event":
            if not self.operator_event:
                return ""
            return json.dumps(self.operator_event)
        if comment == "eks-platform-snapshot":
            snapshot = self.eks_snapshot_queue.pop(0) if self.eks_snapshot_queue else {}
            sections = []
            for key, payload in snapshot.items():
                sections.extend([
                    f"__SCRUM53_{key.upper()}_BEGIN__",
                    json.dumps(payload),
                    f"__SCRUM53_{key.upper()}_END__",
                ])
            return "\n".join(sections)
        if comment == "run-end-check":
            return self.run_end_queue.pop(0) if self.run_end_queue else "present"
        raise AssertionError(f"unrouted SSM comment: {comment}")


class FakeAws:
    def __init__(self) -> None:
        self.target_health_queue: list[dict[str, str]] = []
        self.activities_queue: list[list[dict]] = []
        self.refreshes_queue: list[list[dict]] = []
        self.asg_capacity = {"MinSize": 2, "DesiredCapacity": 2, "MaxSize": 4}
        self.calls: list[tuple[str, str]] = []

    def call(self, args, *, timeout: float = 60):
        self.calls.append((args[0], args[1]))
        if args[:2] == ["elbv2", "describe-target-health"] or tuple(args[:2]) == ("elbv2", "describe-target-health"):
            health = self.target_health_queue.pop(0) if self.target_health_queue else {}
            return {
                "TargetHealthDescriptions": [
                    {"Target": {"Id": target}, "TargetHealth": {"State": state}}
                    for target, state in health.items()
                ]
            }
        if tuple(args[:2]) == ("autoscaling", "describe-scaling-activities"):
            activities = self.activities_queue.pop(0) if self.activities_queue else []
            return {"Activities": activities}
        if tuple(args[:2]) == ("autoscaling", "describe-instance-refreshes"):
            refreshes = self.refreshes_queue.pop(0) if self.refreshes_queue else []
            return {"InstanceRefreshes": refreshes}
        if tuple(args[:2]) == ("autoscaling", "describe-auto-scaling-groups"):
            return {"AutoScalingGroups": [dict(self.asg_capacity)]}
        if tuple(args[:2]) == ("eks", "describe-nodegroup"):
            return {
                "nodegroup": {
                    "clusterName": "kdt-travelplanner-dev-eks",
                    "nodegroupName": "kdt-travelplanner-dev-eks-nodes",
                    "status": "ACTIVE",
                    "scalingConfig": {"minSize": 2, "desiredSize": 2, "maxSize": 4},
                }
            }
        raise AssertionError(f"unrouted AWS call: {args[:2]}")


class FakeMutations:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.exit_code = 0

    def execute(self, spec, *, timeout: float):
        self.executed.append(spec["kind"])
        return self.exit_code, "", "" if self.exit_code == 0 else "mutation failed"


def utc(clock: FakeClock, offset: float = 0.0) -> str:
    return (
        datetime.fromtimestamp(clock.current + offset, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def write_approval(directory: Path, name: str = "approval.json") -> tuple[str, str]:
    path = directory / name
    path.write_text(json.dumps({"gate": "approved"}), encoding="utf-8")
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def base_config(directory: Path, scenario: str = "B-02", run_id: str = "aws-b02-test-1") -> dict:
    approval_path, approval_sha = write_approval(directory)
    config = {
        "contractVersion": MODULE.CONTRACT_VERSION,
        "scenario": scenario,
        "runId": run_id,
        "region": "ap-northeast-2",
        "environment": "dev-runtime",
        "rate": 20,
        "controlDir": str(directory / "control"),
        "expectedHealthyTargets": 2,
        "runner": {
            "instanceId": "i-0123456789abcdef0",
            "repositoryRoot": "/opt/travel-planner",
            "runDir": f"evidence/aws-recovery/{run_id}",
        },
        "target": {
            "asgName": "kdt-travelplanner-dev-backend",
            "targetGroupArn": (
                "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:"
                "targetgroup/kdt-travelplanner-dev-backend/0123456789abcdef"
            ),
            "instanceId": "i-0aaaaaaaaaaaaaaa1",
        },
        "preflightCommand": [
            "scripts/loadtest/aws/orchestrate-aws-recovery.sh",
            "preflight",
            "--run-id",
            run_id,
        ],
        "workloadCommand": [
            "scripts/loadtest/aws/orchestrate-aws-recovery.sh",
            "run",
            "--run-id",
            run_id,
        ],
        "timing": {
            "warmupSeconds": 1,
            "normalWindowSeconds": 1,
            "pollSeconds": 0,
            "detectorTimeoutSeconds": 60,
            "runEndTimeoutSeconds": 60,
        },
        "t1Mutation": {
            "kind": "b02-terminate",
            "argv": [
                "python3",
                "scripts/loadtest/aws/actions/b02-one-instance-replacement.py",
                "--run-id",
                run_id,
                "execute",
                "--approval-file",
                approval_path,
            ],
            "approvalFile": approval_path,
            "approvalSha256": approval_sha,
        },
        "t4Mutation": None,
    }
    if scenario in ("R-03", "R-05", "R-07"):
        plan_path = directory / "fault.tfplan"
        plan_path.write_text("saved-plan", encoding="utf-8")
        plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        restore_path = directory / "restore.tfplan"
        restore_path.write_text("restore-plan", encoding="utf-8")
        restore_sha = hashlib.sha256(restore_path.read_bytes()).hexdigest()
        approval2, approval2_sha = write_approval(directory, "restore-approval.json")
        config["t1Mutation"] = {
            "kind": "terraform-apply",
            "argv": ["terraform", "apply", str(plan_path)],
            "planFile": str(plan_path),
            "planSha256": plan_sha,
            "approvalFile": approval_path,
            "approvalSha256": approval_sha,
        }
        config["operatorRecovery"] = {
            "mode": "manual",
            "requiredActions": ["cancel-refresh", "restore-healthy-image"],
        }
    if scenario == "R-01":
        plan_path = directory / "experiment.tfplan"
        plan_path.write_text("experiment-plan", encoding="utf-8")
        plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        config["t1Mutation"] = {
            "kind": "terraform-apply",
            "argv": ["terraform", "apply", str(plan_path)],
            "planFile": str(plan_path),
            "planSha256": plan_sha,
            "approvalFile": approval_path,
            "approvalSha256": approval_sha,
        }
        config["runId"] = run_id
    return config


def build_coordinator(directory: Path, config: dict):
    clock = FakeClock()
    state = MODULE.CoordinatorState(
        Path(config["controlDir"]) / "coordinator-state.json",
        config["runId"],
        config["scenario"],
        clock,
    )
    ssm = FakeSsm(clock)
    aws = FakeAws()
    mutations = FakeMutations()
    coordinator = MODULE.Coordinator(
        config, state, aws=aws, ssm=ssm, mutations=mutations, clock=clock, log=lambda _: None
    )
    return coordinator, aws, ssm, mutations, clock, state


class ConfigContractTests(unittest.TestCase):
    def test_config_rejects_mismatched_run_id_prefix(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, run_id="aws-r01-test-1")
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "prefix"):
                MODULE.load_config(path)

    def test_config_accepts_compact_scrum43_scenario_id(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-01", run_id="scrum43-r01-test-1")
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            loaded = MODULE.load_config(path)
            self.assertEqual(loaded["runId"], "scrum43-r01-test-1")

    def test_config_rejects_auto_approve_terraform(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-01", run_id="aws-r01-test-1")
            config["t1Mutation"]["argv"] = ["terraform", "apply", "-auto-approve", config["t1Mutation"]["planFile"]]
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "auto-approve"):
                MODULE.load_config(path)

    def test_config_requires_saved_plan_digest_for_terraform(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-01", run_id="aws-r01-test-1")
            del config["t1Mutation"]["planSha256"]
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "planSha256"):
                MODULE.load_config(path)

    def test_config_forbids_t4_mutation_outside_restore_scenarios(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            config["t4Mutation"] = dict(config["t1Mutation"])
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "t4Mutation"):
                MODULE.load_config(path)

    def test_b02_requires_adapter_execute_with_approval(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            config["t1Mutation"]["argv"] = ["aws", "autoscaling", "terminate-instance-in-auto-scaling-group"]
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "adapter"):
                MODULE.load_config(path)


class DryRunTests(unittest.TestCase):
    def test_dry_run_reports_zero_mutations(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            report = MODULE.dry_run_report(config)
            self.assertEqual(report["mutations"], [])
            self.assertEqual(report["mode"], "dry-run")
            self.assertTrue(report["mutationChecks"][0]["approvalDigestMatches"])

    def test_forbidden_mutation_port_always_raises(self) -> None:
        port = MODULE.ForbiddenMutationPort()
        with self.assertRaisesRegex(MODULE.CoordinatorError, "dry-run"):
            port.execute({"kind": "terraform-apply", "argv": ["terraform", "apply"]}, timeout=1)


class StateMachineTests(unittest.TestCase):
    def test_platform_high_watermark_keeps_readiness_when_snapshot_is_skipped(self) -> None:
        previous = {"deployment": {"status": {"replicas": 2, "availableReplicas": 2, "readyReplicas": 2}}}
        current = {"deployment": {"status": {"replicas": 1, "availableReplicas": 0, "readyReplicas": 0}}}
        result = MODULE.platform_high_watermark(previous, current)
        self.assertEqual(result["deployment"]["status"]["availableReplicas"], 2)

    def test_state_refuses_out_of_order_steps(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            state = MODULE.CoordinatorState(
                directory / "state.json", "aws-b02-test-1", "B-02", FakeClock()
            )
            with self.assertRaisesRegex(MODULE.CoordinatorError, "cannot be recorded"):
                state.record("t1")

    def test_state_refuses_duplicate_steps(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            state = MODULE.CoordinatorState(
                directory / "state.json", "aws-b02-test-1", "B-02", FakeClock()
            )
            state.record("preflight")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "already recorded"):
                state.record("preflight")

    def test_state_rejects_gapped_persisted_steps(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            path = directory / "state.json"
            payload = {
                "contractVersion": MODULE.CONTRACT_VERSION,
                "runId": "aws-b02-test-1",
                "scenario": "B-02",
                "steps": {"preflight": {"recordedAtUtc": "2026-08-12T00:00:00.000Z"},
                          "t1": {"recordedAtUtc": "2026-08-12T00:10:00.000Z"}},
                "mutations": [],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "missing earlier step"):
                MODULE.CoordinatorState(path, "aws-b02-test-1", "B-02", FakeClock())

    def test_state_rejects_run_id_mismatch(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            path = directory / "state.json"
            MODULE.CoordinatorState(path, "aws-b02-test-1", "B-02", FakeClock())
            with self.assertRaisesRegex(MODULE.CoordinatorError, "runId"):
                MODULE.CoordinatorState(path, "aws-b02-test-2", "B-02", FakeClock())

    def test_observation_can_record_skipped_platform_state_without_a_step_gap(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            state = MODULE.CoordinatorState(
                directory / "state.json", "aws-b02-test-1", "B-02", FakeClock()
            )
            state.record_observation("asg-activities", "not_observed", {"reason": "poll interval"})
            state.record_observation("asg-activities", "observed", {"terminal": "replacement-healthy"})
            state.record("preflight")
            self.assertEqual(
                [item["status"] for item in state.observations], ["not_observed", "observed"]
            )
            self.assertTrue(state.is_done("preflight"))


class MutationGateTests(unittest.TestCase):
    def test_t1_refuses_without_pre_t1_window(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            coordinator, _, _, mutations, _, _ = build_coordinator(directory, config)
            with self.assertRaisesRegex(MODULE.CoordinatorError, "pre-T1"):
                coordinator.step_t1()
            self.assertEqual(mutations.executed, [])

    def test_t1_refuses_when_workload_is_silent(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            coordinator, _, ssm, mutations, _, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0", "pre-t1-window"):
                state.record(step)
            ssm.stats_queue = [{"status": "ok", "operations": 0, "successful": 0,
                                "unexpectedErrors": 0, "contractFailures": 0}]
            with self.assertRaisesRegex(MODULE.CoordinatorError, "active workload"):
                coordinator.step_t1()
            self.assertEqual(mutations.executed, [])

    def test_tampered_approval_digest_blocks_mutation(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            coordinator, _, ssm, mutations, _, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0", "pre-t1-window"):
                state.record(step)
            Path(config["t1Mutation"]["approvalFile"]).write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CoordinatorError, "approval"):
                coordinator.step_t1()
            self.assertEqual(mutations.executed, [])

    def test_pre_t1_window_blocks_below_capacity_floor(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            coordinator, _, ssm, _, _, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0"):
                state.record(step)
            ssm.stats_queue = [{"status": "ok", "operations": 10, "successful": 10,
                                "unexpectedErrors": 0, "contractFailures": 0}]
            with self.assertRaisesRegex(MODULE.CoordinatorError, "capacity floor"):
                coordinator.step_pre_t1_window()

    def test_pre_t1_window_uses_core_operation_share(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            config["coreOperationShare"] = 0.5
            coordinator, _, ssm, _, _, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0"):
                state.record(step)
            ssm.stats_queue = [{"status": "ok", "operations": 10, "successful": 10,
                                "unexpectedErrors": 0, "contractFailures": 0}]
            coordinator.step_pre_t1_window()

    def test_pre_t1_window_blocks_on_unexpected_errors(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            coordinator, _, ssm, _, _, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0"):
                state.record(step)
            ssm.stats_queue = [{"status": "ok", "operations": 100, "successful": 100,
                                "unexpectedErrors": 1, "contractFailures": 0}]
            with self.assertRaisesRegex(MODULE.CoordinatorError, "unexpected errors"):
                coordinator.step_pre_t1_window()


class B02LifecycleTests(unittest.TestCase):
    def _run_full(self, directory: Path):
        config = base_config(directory)
        coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
        target = config["target"]["instanceId"]
        t1_iso = "2026-08-12T00:00:00.000Z"
        aws.target_health_queue = [
            {target: "draining", "i-0bbbbbbbbbbbbbbb2": "healthy"},  # T2
            {"i-0ccccccccccccccc3": "healthy", "i-0bbbbbbbbbbbbbbb2": "healthy"},  # T5
            {"i-0ccccccccccccccc3": "healthy", "i-0bbbbbbbbbbbbbbb2": "healthy"},  # readback
        ]
        far_future = "2126-01-01T00:00:00.000Z"
        aws.activities_queue = [
            [{"Description": f"Terminating EC2 instance: {target}", "StartTime": far_future}],  # T3
            [{"Description": "Launching a new EC2 instance: i-0ccccccccccccccc3", "StartTime": far_future}],  # T4
        ]
        coordinator.run()
        return coordinator, aws, ssm, mutations, state

    def test_full_lifecycle_records_events_in_order(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            coordinator, aws, ssm, mutations, state = self._run_full(directory)
            recorded = [event for event, _ in ssm.events]
            self.assertEqual(recorded, ["T0", "T1", "T2", "T3", "T4", "T5"])
            self.assertEqual(mutations.executed, ["b02-terminate"])
            for step in MODULE.STEPS:
                self.assertTrue(state.is_done(step), f"step incomplete: {step}")
            readback = json.loads(
                (Path(coordinator.config["controlDir"]) / "restoration-readback.json").read_text()
            )
            self.assertEqual(readback["capacity"], {"minSize": 2, "desiredCapacity": 2, "maxSize": 4})
            self.assertEqual(len(readback["mutationsExecuted"]), 1)

    def test_resume_skips_completed_steps_without_new_mutations(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            coordinator, aws, ssm, mutations, state = self._run_full(directory)
            config = coordinator.config
            resumed, aws2, ssm2, mutations2, clock2, state2 = build_coordinator(directory, config)
            ssm2.fail_comments = {"recovery-preflight", "recovery-workload-start"}
            resumed.run()
            self.assertEqual(mutations2.executed, [])
            self.assertEqual(ssm2.events, [])


class ScenarioDetectorTests(unittest.TestCase):
    def test_r07_t3_comes_from_k6_error_detection(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-07", run_id="aws-r07-test-1")
            coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0", "pre-t1-window", "t1", "t2"):
                state.record(step)
            ssm.stats_queue = [
                {"status": "ok", "operations": 100, "successful": 100, "unexpectedErrors": 0, "contractFailures": 0},
                {"status": "ok", "operations": 100, "successful": 90, "unexpectedErrors": 10, "contractFailures": 0},
            ]
            detail = coordinator._detect_t3()
            self.assertIn("Core API 5xx", detail)
            self.assertNotIn(("elbv2", "describe-target-health"), aws.calls)

    def test_r01_t3_blocks_on_user_visible_errors(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-01", run_id="aws-r01-test-1")
            coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
            ssm.stats_queue = [
                {"status": "ok", "operations": 100, "successful": 90, "unexpectedErrors": 10, "contractFailures": 0}
            ]
            with self.assertRaisesRegex(MODULE.CoordinatorError, "user-visible errors"):
                coordinator._detect_t3()

    def test_r03_t4_waits_for_human_restore_without_mutation(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-03", run_id="aws-r03-test-1")
            coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
            state.record("preflight")
            state.record("workload-start")
            state.record("warmup")
            state.record("t0")
            state.record("pre-t1-window")
            state.record("t1")
            state.record("t2")
            state.record("t3")
            ssm.operator_event = {
                "ts": utc(clock),
                "event": "OPERATOR_RECOVERY",
                "detail": "refresh cancelled and known-good image restored",
                "actor": "operator",
            }
            aws.target_health_queue = [{
                "i-0bbbbbbbbbbbbbbb2": "healthy",
                "i-0ccccccccccccccc3": "healthy",
            }]
            detail = coordinator._detect_t4()
            self.assertIn("human operator recovery", detail)
            self.assertEqual(mutations.executed, [])

    def test_r03_t4_does_not_advance_on_health_without_operator_event(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-03", run_id="aws-r03-test-2")
            coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0", "pre-t1-window", "t1", "t2", "t3"):
                state.record(step)
            aws.target_health_queue = [{
                "i-0bbbbbbbbbbbbbbb2": "healthy",
                "i-0ccccccccccccccc3": "healthy",
            }]
            coordinator.detector_timeout_seconds = 0
            with self.assertRaisesRegex(MODULE.CoordinatorError, "detector timed out"):
                coordinator._detect_t4()
            self.assertEqual(mutations.executed, [])

    def test_r03_t4_rejects_automation_actor_even_when_targets_are_healthy(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-03", run_id="aws-r03-test-3")
            coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0", "pre-t1-window", "t1", "t2", "t3"):
                state.record(step)
            ssm.operator_event = {"ts": utc(clock), "event": "OPERATOR_RECOVERY", "actor": "automation"}
            aws.target_health_queue = [{
                "i-0bbbbbbbbbbbbbbb2": "healthy",
                "i-0ccccccccccccccc3": "healthy",
            }]
            coordinator.detector_timeout_seconds = 0
            with self.assertRaisesRegex(MODULE.CoordinatorError, "detector timed out"):
                coordinator._detect_t4()
            self.assertEqual(mutations.executed, [])

    def test_eks_readiness_uses_platform_snapshot_and_never_issues_restore(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory, scenario="R-03", run_id="aws-r03-eks-test-1")
            config["platform"] = "eks"
            config["target"] = {
                "clusterName": "kdt-travelplanner-dev-eks",
                "nodeGroupName": "kdt-travelplanner-dev-eks-nodes",
                "targetGroupArn": config["target"]["targetGroupArn"],
            }
            coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
            for step in ("preflight", "workload-start", "warmup", "t0", "pre-t1-window", "t1", "t2"):
                state.record(step)
            ssm.eks_snapshot_queue = [{
                "deployment": {"status": {"replicas": 2, "updatedReplicas": 2, "availableReplicas": 1, "readyReplicas": 1}},
                "pods": {"items": []},
                "hpa": {"status": {}},
            }]
            aws.target_health_queue = [{"10.20.1.11": "healthy", "10.20.2.11": "healthy"}]
            detail = coordinator._detect_t3()
            self.assertIn("readiness failure", detail)
            self.assertEqual(mutations.executed, [])

    def test_b02_t5_rejects_terminated_instance_as_recovery(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            config = base_config(directory)
            coordinator, aws, ssm, mutations, clock, state = build_coordinator(directory, config)
            target = config["target"]["instanceId"]
            aws.target_health_queue = [
                {target: "healthy", "i-0bbbbbbbbbbbbbbb2": "healthy"},
                {"i-0ccccccccccccccc3": "healthy", "i-0bbbbbbbbbbbbbbb2": "healthy"},
            ]
            detail = coordinator._detect_t5()
            self.assertEqual(detail, "2 targets healthy")
            # Two polls happened: the first (terminated instance still healthy) was rejected.
            self.assertEqual(aws.target_health_queue, [])


class ReadOnlyAwsPortTests(unittest.TestCase):
    def test_aws_port_refuses_mutating_verbs(self) -> None:
        class Recorder:
            def run(self, argv, *, timeout, cwd=None):
                raise AssertionError("must not run")

        port = MODULE.AwsPort(Recorder(), "ap-northeast-2")
        with self.assertRaisesRegex(MODULE.CoordinatorError, "read-only"):
            port.call(["autoscaling", "terminate-instance-in-auto-scaling-group", "--instance-id", "i-1"])
        with self.assertRaisesRegex(MODULE.CoordinatorError, "read-only"):
            port.call(["autoscaling", "start-instance-refresh"])


if __name__ == "__main__":
    unittest.main()
