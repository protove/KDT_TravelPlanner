#!/usr/bin/env python3
"""Fail-closed live coordinator for AWS Recovery experiments.

The coordinator drives one bounded Recovery lifecycle on a control machine:

    preflight -> workload start (SSM, async) -> warm-up -> T0
    -> pre-T1 normal window -> T1 approved mutation -> T2..T5 detection
    -> post-T5 SLO window -> RUN_END -> restoration read-back

It contains no terminate/refresh/Terraform logic of its own. The only
mutating step executes an operator-approved command whose file digests are
re-verified immediately before execution, and it can never run before the
pre-T1 window step has completed inside an active workload. Every phase
transition is checkpointed to a durable state file so a resumed invocation
continues instead of repeating side effects.

All AWS access goes through injected ports so the whole state machine is
testable without credentials, boto3, Docker, or a live account.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

CONTRACT_VERSION = "aws-recovery-live-coordinator-v1"
APPROVED_REGION_RE = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+$")
RUN_ID_RE = re.compile(r"^aws-(b02|r01|r03|r05|r07)-[A-Za-z0-9._-]{1,80}$")
INSTANCE_ID_RE = re.compile(r"^i-[0-9a-f]{8,32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DETAIL_MAX = 200

SCENARIO_PREFIX = {
    "B-02": "aws-b02-",
    "R-01": "aws-r01-",
    "R-03": "aws-r03-",
    "R-05": "aws-r05-",
    "R-07": "aws-r07-",
}
RESTORE_SCENARIOS = {"R-03", "R-05", "R-07"}

STEPS = (
    "preflight",
    "workload-start",
    "warmup",
    "t0",
    "pre-t1-window",
    "t1",
    "t2",
    "t3",
    "t4",
    "t5",
    "post-t5-window",
    "run-end",
    "restoration-readback",
)

MUTATION_KINDS = {"b02-terminate", "terraform-apply"}


class CoordinatorError(ValueError):
    """Raised when the coordinator must stop instead of guessing."""


def utc_iso(now: float) -> str:
    return (
        datetime.fromtimestamp(now, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_detail(detail: str) -> str:
    single_line = " ".join(str(detail).split())
    return single_line[:DETAIL_MAX]


class ClockPort(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class CommandPort(Protocol):
    def run(self, argv: Sequence[str], *, timeout: float, cwd: str | None = None) -> tuple[int, str, str]: ...


class SubprocessCommandPort:
    def run(self, argv: Sequence[str], *, timeout: float, cwd: str | None = None) -> tuple[int, str, str]:
        completed = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
        )
        return completed.returncode, completed.stdout, completed.stderr


class AwsPort:
    """Read-only AWS CLI JSON port; mutating verbs are refused."""

    _FORBIDDEN = (
        "terminate", "delete", "create", "put", "update", "modify", "start-instance-refresh",
        "cancel", "set-desired-capacity", "detach", "attach", "reboot", "stop", "run-instances",
        "apply", "destroy",
    )

    def __init__(self, commands: CommandPort, region: str, profile: str | None = None) -> None:
        self._commands = commands
        self._region = region
        self._profile = profile

    def call(self, args: Sequence[str], *, timeout: float = 60) -> dict[str, Any]:
        for token in args:
            lowered = str(token).lower()
            for verb in self._FORBIDDEN:
                if lowered == verb or lowered.startswith(f"{verb}-"):
                    raise CoordinatorError(f"read-only AWS port refused mutating verb: {token}")
        argv = ["aws", *args, "--region", self._region, "--output", "json"]
        if self._profile:
            argv += ["--profile", self._profile]
        code, stdout, stderr = self._commands.run(argv, timeout=timeout)
        if code != 0:
            raise CoordinatorError(f"AWS read failed ({args[0]} {args[1]}): {stderr.strip()[:300]}")
        return json.loads(stdout) if stdout.strip() else {}


class SsmPort:
    """Run one shell command list on the approved Runner via SSM and return stdout."""

    def __init__(
        self,
        commands: CommandPort,
        region: str,
        instance_id: str,
        clock: ClockPort,
        profile: str | None = None,
    ) -> None:
        self._commands = commands
        self._region = region
        self._instance = instance_id
        self._clock = clock
        self._profile = profile

    def _aws(self, args: Sequence[str], timeout: float = 60) -> dict[str, Any]:
        argv = ["aws", *args, "--region", self._region, "--output", "json"]
        if self._profile:
            argv += ["--profile", self._profile]
        code, stdout, stderr = self._commands.run(argv, timeout=timeout)
        if code != 0:
            raise CoordinatorError(f"SSM call failed: {stderr.strip()[:300]}")
        return json.loads(stdout) if stdout.strip() else {}

    def run(self, command: str, *, timeout_seconds: int = 120, comment: str = "recovery-coordinator") -> str:
        sent = self._aws(
            [
                "ssm", "send-command",
                "--instance-ids", self._instance,
                "--document-name", "AWS-RunShellScript",
                "--comment", comment[:100],
                "--parameters", json.dumps({"commands": [command], "executionTimeout": [str(max(timeout_seconds, 30))]}),
            ],
            timeout=60,
        )
        command_id = sent.get("Command", {}).get("CommandId")
        if not command_id:
            raise CoordinatorError("SSM send-command returned no CommandId")
        deadline = self._clock.now() + timeout_seconds + 90
        while True:
            if self._clock.now() > deadline:
                raise CoordinatorError(f"SSM command timed out: {comment}")
            self._clock.sleep(2)
            invocation = self._aws(
                ["ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", self._instance],
                timeout=60,
            )
            status = invocation.get("Status")
            if status in ("Pending", "InProgress", "Delayed"):
                continue
            if status == "Success":
                return invocation.get("StandardOutputContent", "")
            raise CoordinatorError(
                f"SSM command failed with status {status}: "
                f"{(invocation.get('StandardErrorContent') or '')[:300]}"
            )


class MutationPort:
    """Executes exactly one approved mutating command per call site."""

    def __init__(self, commands: CommandPort) -> None:
        self._commands = commands
        self.executed: list[str] = []

    def execute(self, spec: dict[str, Any], *, timeout: float) -> tuple[int, str, str]:
        argv = spec["argv"]
        code, stdout, stderr = self._commands.run(argv, timeout=timeout, cwd=spec.get("cwd"))
        self.executed.append(spec["kind"])
        return code, stdout, stderr


class ForbiddenMutationPort:
    """Dry-run stand-in: any call is a contract violation."""

    def execute(self, spec: dict[str, Any], *, timeout: float) -> tuple[int, str, str]:
        raise CoordinatorError("dry-run must never execute a mutation")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CoordinatorError(message)


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CoordinatorError(f"cannot read coordinator config: {error}") from error
    _require(isinstance(config, dict), "coordinator config must be a JSON object")
    _require(config.get("contractVersion") == CONTRACT_VERSION, "config contractVersion mismatch")
    scenario = config.get("scenario")
    _require(scenario in SCENARIO_PREFIX, "config scenario must be B-02/R-01/R-03/R-05/R-07")
    run_id = config.get("runId", "")
    _require(bool(RUN_ID_RE.fullmatch(str(run_id))), "config runId is not an approved Recovery run id")
    _require(str(run_id).startswith(SCENARIO_PREFIX[scenario]), "config runId prefix does not match scenario")
    _require(bool(APPROVED_REGION_RE.fullmatch(str(config.get("region", "")))), "config region is invalid")
    _require(config.get("environment") == "dev-runtime", "config environment must be dev-runtime")

    runner = config.get("runner")
    _require(isinstance(runner, dict), "config.runner must be an object")
    _require(bool(INSTANCE_ID_RE.fullmatch(str(runner.get("instanceId", "")))), "runner.instanceId is invalid")
    _require(
        isinstance(runner.get("repositoryRoot"), str) and runner["repositoryRoot"].startswith("/"),
        "runner.repositoryRoot must be an absolute path",
    )
    run_dir = runner.get("runDir", "")
    _require(
        isinstance(run_dir, str)
        and run_dir == f"evidence/aws-recovery/{run_id}"
        and ".." not in Path(run_dir).parts,
        "runner.runDir must be evidence/aws-recovery/<runId>",
    )

    target = config.get("target")
    _require(isinstance(target, dict), "config.target must be an object")
    for field in ("asgName", "targetGroupArn"):
        _require(isinstance(target.get(field), str) and target[field], f"target.{field} is required")
    if scenario == "B-02":
        _require(
            bool(INSTANCE_ID_RE.fullmatch(str(target.get("instanceId", "")))),
            "B-02 requires target.instanceId",
        )

    for name, script, mode in (
        ("preflightCommand", "scripts/loadtest/aws/orchestrate-aws-recovery.sh", "preflight"),
        ("workloadCommand", "scripts/loadtest/aws/orchestrate-aws-recovery.sh", "run"),
    ):
        command = config.get(name)
        _require(isinstance(command, list) and command, f"config.{name} must be a non-empty argv list")
        _require(all(isinstance(item, str) for item in command), f"config.{name} must contain strings")
        _require(command[0] == script, f"config.{name} must invoke {script}")
        _require(mode in command, f"config.{name} must select the {mode} mode")

    timing = config.get("timing", {})
    _require(isinstance(timing, dict), "config.timing must be an object")
    rate = config.get("rate")
    _require(
        isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0,
        "config.rate must be the positive frozen D-005 arrival rate",
    )

    t1 = config.get("t1Mutation")
    _validate_mutation_spec(t1, "t1Mutation", scenario)
    t4 = config.get("t4Mutation")
    if scenario in RESTORE_SCENARIOS:
        _validate_mutation_spec(t4, "t4Mutation", scenario)
    else:
        _require(t4 is None, f"{scenario} must not define t4Mutation")
    return config


def _validate_mutation_spec(spec: Any, label: str, scenario: str) -> None:
    _require(isinstance(spec, dict), f"config.{label} must be an object")
    kind = spec.get("kind")
    _require(kind in MUTATION_KINDS, f"{label}.kind must be one of {sorted(MUTATION_KINDS)}")
    if scenario == "B-02":
        _require(kind == "b02-terminate", "B-02 T1 mutation must use the b02-terminate adapter")
    else:
        _require(kind == "terraform-apply", f"{scenario} mutations must be exact terraform applies")
    argv = spec.get("argv")
    _require(isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv), f"{label}.argv must be a string list")
    if kind == "b02-terminate":
        _require(
            argv[0].endswith("actions/b02-one-instance-replacement.py") or (
                argv[0] == "python3" and len(argv) > 1 and argv[1].endswith("actions/b02-one-instance-replacement.py")
            ),
            f"{label}.argv must invoke the B-02 adapter",
        )
        _require("execute" in argv, f"{label}.argv must use the adapter execute mode")
        _require("--approval-file" in argv, f"{label}.argv must pass --approval-file")
    else:
        _require(argv[0] == "terraform" and "apply" in argv, f"{label}.argv must be a terraform apply")
        _require("-auto-approve" not in argv, f"{label}.argv must not use -auto-approve")
        _require(isinstance(spec.get("planFile"), str) and spec["planFile"], f"{label}.planFile is required")
        _require(argv[-1] == spec["planFile"] or Path(argv[-1]).name == Path(spec["planFile"]).name, f"{label}.argv must apply the exact saved plan")
        _require(bool(SHA256_RE.fullmatch(str(spec.get("planSha256", "")))), f"{label}.planSha256 is required")
    approval = spec.get("approvalFile")
    _require(isinstance(approval, str) and approval, f"{label}.approvalFile is required")
    _require(bool(SHA256_RE.fullmatch(str(spec.get("approvalSha256", "")))), f"{label}.approvalSha256 is required")


class CoordinatorState:
    """Durable, append-only step checkpoints for one run."""

    def __init__(self, path: Path, run_id: str, scenario: str, clock: ClockPort) -> None:
        self._path = path
        self._clock = clock
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise CoordinatorError(f"cannot read coordinator state: {error}") from error
            _require(payload.get("contractVersion") == CONTRACT_VERSION, "state contractVersion mismatch")
            _require(payload.get("runId") == run_id, "state runId does not match config")
            _require(payload.get("scenario") == scenario, "state scenario does not match config")
            steps = payload.get("steps")
            _require(isinstance(steps, dict), "state steps must be an object")
            seen_gap = False
            for step in STEPS:
                if step in steps:
                    _require(not seen_gap, f"state records step {step} after a missing earlier step")
                else:
                    seen_gap = True
            self._payload = payload
        else:
            self._payload = {
                "contractVersion": CONTRACT_VERSION,
                "runId": run_id,
                "scenario": scenario,
                "steps": {},
                "mutations": [],
            }
            self._write()

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def is_done(self, step: str) -> bool:
        return step in self._payload["steps"]

    def step_epoch(self, step: str) -> float:
        entry = self._payload["steps"].get(step)
        _require(isinstance(entry, dict), f"step has not been recorded: {step}")
        value = str(entry.get("recordedAtUtc", ""))
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

    def record(self, step: str, detail: dict[str, Any] | None = None) -> None:
        _require(step in STEPS, f"unknown coordinator step: {step}")
        _require(not self.is_done(step), f"step already recorded: {step}")
        index = STEPS.index(step)
        for earlier in STEPS[:index]:
            _require(self.is_done(earlier), f"step {step} cannot be recorded before {earlier}")
        self._payload["steps"][step] = {
            "recordedAtUtc": utc_iso(self._clock.now()),
            **({"detail": detail} if detail else {}),
        }
        self._write()

    def record_mutation(self, kind: str, argv_sha256: str) -> None:
        self._payload["mutations"].append(
            {"kind": kind, "argvSha256": argv_sha256, "executedAtUtc": utc_iso(self._clock.now())}
        )
        self._write()

    @property
    def mutations(self) -> list[dict[str, Any]]:
        return list(self._payload["mutations"])


class Coordinator:
    def __init__(
        self,
        config: dict[str, Any],
        state: CoordinatorState,
        *,
        aws: AwsPort,
        ssm: SsmPort,
        mutations: MutationPort | ForbiddenMutationPort,
        clock: ClockPort,
        log: Callable[[str], None] = lambda message: print(message, flush=True),
    ) -> None:
        self.config = config
        self.state = state
        self.aws = aws
        self.ssm = ssm
        self.mutations = mutations
        self.clock = clock
        self.log = log
        timing = config.get("timing", {})
        self.warmup_seconds = int(timing.get("warmupSeconds", 180))
        self.normal_window_seconds = int(timing.get("normalWindowSeconds", 120))
        self.poll_seconds = int(timing.get("pollSeconds", 20))
        self.detector_timeout_seconds = int(timing.get("detectorTimeoutSeconds", 900))
        self.run_end_timeout_seconds = int(timing.get("runEndTimeoutSeconds", 2400))
        self.minimum_window_ratio = float(timing.get("minimumWindowSuccessRatio", 0.9))

    # ----- runner helpers ---------------------------------------------------

    def _runner_shell(self, argv: Sequence[str], *, timeout_seconds: int, comment: str, background: bool = False) -> str:
        repo = self.config["runner"]["repositoryRoot"]
        quoted = " ".join(shlex.quote(item) for item in argv)
        command = f"cd {shlex.quote(repo)} && {quoted}"
        if background:
            command = (
                f"cd {shlex.quote(repo)} && nohup {quoted} "
                f">> {shlex.quote(self.config['runner']['runDir'])}/coordinator-workload.log 2>&1 & echo started:$!"
            )
        return self.ssm.run(command, timeout_seconds=timeout_seconds, comment=comment)

    def record_event(self, event: str, detail: str) -> None:
        run_dir = self.config["runner"]["runDir"]
        argv = [
            "python3",
            "scripts/loadtest/record-rehearsal-event.py",
            run_dir,
            event,
            sanitize_detail(detail),
            "--actor",
            "automation",
        ]
        self._runner_shell(argv, timeout_seconds=90, comment=f"record-{event}")

    def live_stats(self, window_seconds: int) -> dict[str, Any]:
        argv = [
            "python3",
            "scripts/loadtest/aws/runner-live-stats.py",
            self.config["runner"]["runDir"],
            "--window-seconds",
            str(window_seconds),
        ]
        output = self._runner_shell(argv, timeout_seconds=90, comment="live-stats")
        try:
            payload = json.loads(output.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise CoordinatorError(f"live stats output is not JSON: {error}") from error
        return payload

    # ----- AWS detectors ----------------------------------------------------

    def _target_health(self) -> dict[str, str]:
        payload = self.aws.call(
            [
                "elbv2",
                "describe-target-health",
                "--target-group-arn",
                self.config["target"]["targetGroupArn"],
            ]
        )
        result: dict[str, str] = {}
        for item in payload.get("TargetHealthDescriptions", []):
            target_id = item.get("Target", {}).get("Id")
            state = item.get("TargetHealth", {}).get("State")
            if isinstance(target_id, str) and isinstance(state, str):
                result[target_id] = state
        return result

    def _scaling_activities(self, *, since_step: str = "t1") -> list[dict[str, Any]]:
        payload = self.aws.call(
            [
                "autoscaling",
                "describe-scaling-activities",
                "--auto-scaling-group-name",
                self.config["target"]["asgName"],
                "--max-records",
                "40",
            ]
        )
        cutoff = self.state.step_epoch(since_step) if self.state.is_done(since_step) else 0.0
        recent: list[dict[str, Any]] = []
        for activity in payload.get("Activities", []):
            start = activity.get("StartTime")
            try:
                started = datetime.fromisoformat(str(start).replace("Z", "+00:00")).timestamp()
            except (TypeError, ValueError):
                continue
            # Allow a small clock skew margin so an activity issued at T1 is kept.
            if started >= cutoff - 5:
                recent.append(activity)
        return recent

    def _instance_refreshes(self) -> list[dict[str, Any]]:
        payload = self.aws.call(
            [
                "autoscaling",
                "describe-instance-refreshes",
                "--auto-scaling-group-name",
                self.config["target"]["asgName"],
                "--max-records",
                "10",
            ]
        )
        return payload.get("InstanceRefreshes", [])

    def _poll_until(self, label: str, probe: Callable[[], str | None]) -> str:
        deadline = self.clock.now() + self.detector_timeout_seconds
        while True:
            detail = probe()
            if detail is not None:
                return detail
            if self.clock.now() > deadline:
                raise CoordinatorError(f"detector timed out: {label}")
            self.clock.sleep(self.poll_seconds)

    # ----- steps ------------------------------------------------------------

    def step_preflight(self) -> None:
        output = self._runner_shell(
            self.config["preflightCommand"], timeout_seconds=600, comment="recovery-preflight"
        )
        _require("preflight passed" in output, "runner preflight did not pass")
        self.log("[coordinator] preflight passed on runner")

    def step_workload_start(self) -> None:
        output = self._runner_shell(
            self.config["workloadCommand"],
            timeout_seconds=90,
            comment="recovery-workload-start",
            background=True,
        )
        _require("started:" in output, "workload did not start on runner")
        self.log("[coordinator] workload started on runner")

    def step_warmup(self) -> None:
        deadline = self.clock.now() + self.warmup_seconds + 300
        while True:
            stats = self.live_stats(60)
            if stats.get("status") == "ok" and (stats.get("operations") or 0) > 0:
                break
            _require(self.clock.now() < deadline, "workload produced no traffic during warm-up")
            self.clock.sleep(self.poll_seconds)
        self.clock.sleep(self.warmup_seconds)
        self.log("[coordinator] warm-up window elapsed")

    def step_t0(self) -> None:
        self.record_event("T0", "Recovery steady workload reached T0 after warm-up")

    def step_pre_t1_window(self) -> None:
        self.clock.sleep(self.normal_window_seconds)
        stats = self.live_stats(self.normal_window_seconds)
        _require(stats.get("status") == "ok", "live stats unavailable for the pre-T1 window")
        rate = float(self.config.get("rate", 0) or 0)
        _require(rate > 0, "config.rate must be the frozen D-005 rate")
        expected = rate * self.normal_window_seconds
        successful = float(stats.get("successful") or 0)
        _require(
            successful >= expected * self.minimum_window_ratio,
            f"pre-T1 window below capacity floor: successful={successful} expected>={expected * self.minimum_window_ratio}",
        )
        _require(float(stats.get("unexpectedErrors") or 0) == 0, "pre-T1 window observed unexpected errors")
        _require(float(stats.get("contractFailures") or 0) == 0, "pre-T1 window observed contract failures")
        self.log(f"[coordinator] pre-T1 normal window verified: successful={successful}")

    def _execute_mutation(self, label: str) -> None:
        spec = self.config[label]
        approval_path = Path(spec["approvalFile"])
        _require(approval_path.is_file(), f"{label} approval artifact is missing")
        _require(
            sha256_file(approval_path) == spec["approvalSha256"],
            f"{label} approval artifact digest changed; approval is void",
        )
        if spec["kind"] == "terraform-apply":
            plan_path = Path(spec["planFile"])
            _require(plan_path.is_file(), f"{label} saved plan is missing")
            _require(
                sha256_file(plan_path) == spec["planSha256"],
                f"{label} saved plan digest changed; approval is void",
            )
        argv_sha = hashlib.sha256(json.dumps(spec["argv"]).encode()).hexdigest()
        code, stdout, stderr = self.mutations.execute(spec, timeout=float(spec.get("timeoutSeconds", 900)))
        self.state.record_mutation(spec["kind"], argv_sha)
        _require(code == 0, f"{label} mutation failed: {stderr.strip()[:300]}")

    def step_t1(self) -> None:
        _require(self.state.is_done("pre-t1-window"), "T1 requires a verified pre-T1 window")
        stats = self.live_stats(60)
        _require(
            stats.get("status") == "ok" and (stats.get("operations") or 0) > 0,
            "T1 requires an active workload",
        )
        self.record_event("T1", self.config.get("t1Detail", "approved fault/rollout command issued"))
        self._execute_mutation("t1Mutation")
        self.log("[coordinator] T1 mutation executed")

    # -- scenario detectors, each returns sanitized detail --

    def _detect_t2(self) -> str:
        scenario = self.config["scenario"]
        if scenario == "B-02":
            instance = self.config["target"]["instanceId"]

            def probe() -> str | None:
                state = self._target_health().get(instance)
                if state is None or state != "healthy":
                    return f"terminated target left healthy state (state={state or 'deregistered'})"
                return None

            return self._poll_until("B-02 target exclusion", probe)
        if scenario == "R-07":

            def probe() -> str | None:
                for refresh in self._instance_refreshes():
                    if refresh.get("Status") in ("Successful",):
                        return "fault rollout completed with readiness passing"
                    if refresh.get("Status") in ("InProgress", "Pending") and (refresh.get("PercentageComplete") or 0) >= 50:
                        return "fault rollout reached first replaced target with readiness passing"
                return None

            return self._poll_until("R-07 fault rollout", probe)

        def probe() -> str | None:
            for activity in self._scaling_activities():
                description = str(activity.get("Description", ""))
                if description.startswith("Launching a new EC2 instance"):
                    return "rollout launched a replacement instance"
            for refresh in self._instance_refreshes():
                if refresh.get("Status") in ("InProgress", "Pending"):
                    return "instance refresh in progress"
            return None

        return self._poll_until(f"{scenario} first replacement", probe)

    def _detect_t3(self) -> str:
        scenario = self.config["scenario"]
        if scenario == "B-02":

            def probe() -> str | None:
                instance = self.config["target"]["instanceId"]
                for activity in self._scaling_activities():
                    description = str(activity.get("Description", ""))
                    if "Terminating EC2 instance" in description and instance in description:
                        return "ASG recorded the terminate activity"
                return None

            return self._poll_until("B-02 terminate activity", probe)
        if scenario == "R-01":
            stats = self.live_stats(60)
            _require(
                float(stats.get("unexpectedErrors") or 0) == 0
                and float(stats.get("contractFailures") or 0) == 0,
                "R-01 observed user-visible errors during rollout",
            )
            return "no user-visible errors observed during rolling rollout (marker)"
        if scenario == "R-07":

            def probe() -> str | None:
                stats = self.live_stats(60)
                if float(stats.get("unexpectedErrors") or 0) > 0:
                    return "k6 observed Core API 5xx while readiness stayed healthy"
                return None

            return self._poll_until("R-07 business error detection", probe)

        def probe() -> str | None:
            health = self._target_health()
            unhealthy = [state for state in health.values() if state in ("unhealthy", "initial")]
            if unhealthy:
                return f"readiness failure visible at ALB (states={','.join(sorted(set(unhealthy)))})"
            return None

        return self._poll_until(f"{scenario} readiness failure", probe)

    def _detect_t4(self) -> str:
        scenario = self.config["scenario"]
        if scenario in RESTORE_SCENARIOS:
            self._execute_mutation("t4Mutation")
            return "manual baseline restore apply issued"
        if scenario == "B-02":

            def probe() -> str | None:
                for activity in self._scaling_activities():
                    description = str(activity.get("Description", ""))
                    if description.startswith("Launching a new EC2 instance"):
                        return "ASG replacement launch started"
                return None

            return self._poll_until("B-02 replacement launch", probe)

        def probe() -> str | None:
            for refresh in self._instance_refreshes():
                if refresh.get("Status") == "Successful":
                    return "instance refresh completed"
                if (refresh.get("PercentageComplete") or 0) >= 50:
                    return "instance refresh passed the 50 percent checkpoint"
            return None

        return self._poll_until("R-01 rollout progress", probe)

    def _detect_t5(self) -> str:
        expected_healthy = int(self.config.get("expectedHealthyTargets", 2))
        forbidden = (
            {self.config["target"]["instanceId"]}
            if self.config["scenario"] == "B-02"
            else set()
        )

        def probe() -> str | None:
            health = self._target_health()
            healthy = {target for target, state in health.items() if state == "healthy"}
            others = {target: state for target, state in health.items() if state != "healthy"}
            if len(healthy) >= expected_healthy and not others and not (healthy & forbidden):
                return f"{len(healthy)} targets healthy"
            return None

        return self._poll_until("healthy target recovery", probe)

    def step_post_t5_window(self) -> None:
        self.clock.sleep(self.normal_window_seconds)
        stats = self.live_stats(self.normal_window_seconds)
        _require(stats.get("status") == "ok", "post-T5 live stats unavailable")
        self.log(
            "[coordinator] post-T5 window observed: "
            f"successful={stats.get('successful')} unexpectedErrors={stats.get('unexpectedErrors')}"
        )

    def step_run_end(self) -> None:
        run_dir = self.config["runner"]["runDir"]
        deadline = self.clock.now() + self.run_end_timeout_seconds

        while True:
            output = self._runner_shell(
                ["sh", "-c", f"test -f {shlex.quote(run_dir + '/run-status.json')} && echo present || echo absent"],
                timeout_seconds=60,
                comment="run-end-check",
            )
            if "present" in output:
                break
            _require(self.clock.now() < deadline, "k6 workload did not end within the timeout")
            self.clock.sleep(self.poll_seconds)
        self.log("[coordinator] RUN_END observed on runner")

    def step_restoration_readback(self) -> None:
        asg_payload = self.aws.call(
            [
                "autoscaling",
                "describe-auto-scaling-groups",
                "--auto-scaling-group-names",
                self.config["target"]["asgName"],
            ]
        )
        groups = asg_payload.get("AutoScalingGroups", [])
        _require(len(groups) == 1, "restoration read-back could not resolve the ASG")
        group = groups[0]
        capacity = (group.get("MinSize"), group.get("DesiredCapacity"), group.get("MaxSize"))
        _require(capacity == (2, 2, 4), f"ASG capacity is not restored: {capacity}")
        health = self._target_health()
        healthy = [target for target, state in health.items() if state == "healthy"]
        _require(
            len(healthy) == int(self.config.get("expectedHealthyTargets", 2)),
            f"restored healthy target count mismatch: {sorted(health.values())}",
        )
        readback = {
            "contractVersion": CONTRACT_VERSION,
            "runId": self.config["runId"],
            "scenario": self.config["scenario"],
            "capacity": {"minSize": capacity[0], "desiredCapacity": capacity[1], "maxSize": capacity[2]},
            "healthyTargetCount": len(healthy),
            "mutationsExecuted": self.state.mutations,
            "recordedAtUtc": utc_iso(self.clock.now()),
        }
        control_dir = Path(self.config["controlDir"])
        control_dir.mkdir(parents=True, exist_ok=True)
        (control_dir / "restoration-readback.json").write_text(
            json.dumps(readback, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.log("[coordinator] restoration read-back verified")

    # ----- run loop ----------------------------------------------------------

    def run(self, until: str | None = None) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "preflight": self.step_preflight,
            "workload-start": self.step_workload_start,
            "warmup": self.step_warmup,
            "t0": self.step_t0,
            "pre-t1-window": self.step_pre_t1_window,
            "t1": self.step_t1,
            "t2": lambda: self.record_event("T2", self._detect_t2()),
            "t3": lambda: self.record_event("T3", self._detect_t3()),
            "t4": lambda: self.record_event("T4", self._detect_t4()),
            "t5": lambda: self.record_event("T5", self._detect_t5()),
            "post-t5-window": self.step_post_t5_window,
            "run-end": self.step_run_end,
            "restoration-readback": self.step_restoration_readback,
        }
        for step in STEPS:
            if self.state.is_done(step):
                self.log(f"[coordinator] step already complete: {step}")
            else:
                self.log(f"[coordinator] step start: {step}")
                handlers[step]()
                if step not in ("t2", "t3", "t4", "t5"):
                    self.state.record(step)
                else:
                    self.state.record(step, {"event": step.upper()})
                self.log(f"[coordinator] step done: {step}")
            if until is not None and step == until:
                self.log(f"[coordinator] stopping after requested step: {step}")
                return


def dry_run_report(config: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for label in ("t1Mutation", "t4Mutation"):
        spec = config.get(label)
        if not spec:
            continue
        approval = Path(spec["approvalFile"])
        entry: dict[str, Any] = {"mutation": label, "kind": spec["kind"]}
        entry["approvalFilePresent"] = approval.is_file()
        if approval.is_file():
            entry["approvalDigestMatches"] = sha256_file(approval) == spec["approvalSha256"]
        if spec["kind"] == "terraform-apply":
            plan = Path(spec["planFile"])
            entry["planFilePresent"] = plan.is_file()
            if plan.is_file():
                entry["planDigestMatches"] = sha256_file(plan) == spec["planSha256"]
        checks.append(entry)
    return {
        "contractVersion": CONTRACT_VERSION,
        "mode": "dry-run",
        "runId": config["runId"],
        "scenario": config["scenario"],
        "steps": list(STEPS),
        "mutationChecks": checks,
        "mutations": [],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=None, help="durable state file (defaults to <controlDir>/coordinator-state.json)")
    parser.add_argument("--until", choices=STEPS, default=None)
    parser.add_argument("--aws-profile", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        _require(isinstance(config.get("controlDir"), str) and config["controlDir"], "config.controlDir is required")
        if args.dry_run:
            print(json.dumps(dry_run_report(config), indent=2))
            return 0
        clock = SystemClock()
        state_path = args.state or Path(config["controlDir"]) / "coordinator-state.json"
        state = CoordinatorState(state_path, config["runId"], config["scenario"], clock)
        commands = SubprocessCommandPort()
        coordinator = Coordinator(
            config,
            state,
            aws=AwsPort(commands, config["region"], args.aws_profile),
            ssm=SsmPort(commands, config["region"], config["runner"]["instanceId"], clock, args.aws_profile),
            mutations=MutationPort(commands),
            clock=clock,
        )
        coordinator.run(until=args.until)
    except CoordinatorError as error:
        print(f"[coordinator] blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
