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
RUN_ID_RE = re.compile(r"^(?:aws-(b02|r01|r03|r05|r07)|scrum43-(b02|r01|r03|r05|r07))-[A-Za-z0-9._-]{1,80}$")
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

MUTATION_KINDS = {"b02-terminate", "terraform-apply", "recovery-rollout"}


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


def platform_high_watermark(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Merge monotonic readiness observations across skipped polls."""

    previous = previous or {}
    result = dict(previous)
    for section in ("deployment", "hpa"):
        old_status = previous.get(section, {}).get("status", {}) if isinstance(previous.get(section), dict) else {}
        new_status = current.get(section, {}).get("status", {}) if isinstance(current.get(section), dict) else {}
        merged = dict(old_status) if isinstance(old_status, dict) else {}
        if isinstance(new_status, dict):
            for key in ("replicas", "updatedReplicas", "availableReplicas", "readyReplicas", "currentReplicas", "desiredReplicas"):
                if isinstance(new_status.get(key), int):
                    merged[key] = max(int(merged.get(key, 0) or 0), new_status[key])
        if merged:
            result[section] = {**(previous.get(section, {}) if isinstance(previous.get(section), dict) else {}), "status": merged}
    # Pod/node membership is not monotonic, but retaining the most recent
    # complete section is important when a later SSM poll transiently omits a
    # kubectl section.  Do not manufacture a replacement from a missing poll.
    for section in ("pods", "nodes", "events"):
        if isinstance(current.get(section), dict):
            result[section] = current[section]
    return result


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
    # SCRUM-43 comparison runs use compact scenario IDs (``r01``/``r03``),
    # while the legacy ``aws-*`` IDs retain their historical mapping.  Keep
    # the accepted forms aligned with RUN_ID_RE; the previous check expanded
    # ``R-01`` to ``scrum43-r-01`` and rejected every planned ``scrum43-r01``
    # run before any AWS call was made.
    compact_scenario = scenario.replace("-", "").lower()
    _require(
        str(run_id).startswith(SCENARIO_PREFIX[scenario])
        or str(run_id).startswith(f"scrum43-{compact_scenario}-"),
        "config runId prefix does not match scenario",
    )
    _require(bool(APPROVED_REGION_RE.fullmatch(str(config.get("region", "")))), "config region is invalid")
    _require(config.get("environment") in {"dev-runtime", "dev-eks", "comparison"}, "config environment must be dev-runtime, dev-eks or comparison")
    platform = config.get("platform", "ec2")
    _require(platform in {"ec2", "eks"}, "config platform must be ec2 or eks")

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
    _require(isinstance(target.get("targetGroupArn"), str) and target["targetGroupArn"], "target.targetGroupArn is required")
    if platform == "ec2":
        _require(isinstance(target.get("asgName"), str) and target["asgName"], "target.asgName is required for EC2")
    else:
        _require(isinstance(target.get("clusterName"), str) and target["clusterName"], "target.clusterName is required for EKS")
        _require(isinstance(target.get("nodeGroupName"), str) and target["nodeGroupName"], "target.nodeGroupName is required for EKS")
    if scenario == "B-02":
        target_instance = target.get("instanceId") or target.get("nodeInstanceId")
        _require(
            bool(INSTANCE_ID_RE.fullmatch(str(target_instance or ""))),
            "B-02 requires target.instanceId (EC2) or target.nodeInstanceId (EKS)",
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
    _validate_mutation_spec(t1, "t1Mutation", scenario, platform)
    t4 = config.get("t4Mutation")
    _require(t4 is None, "t4Mutation is forbidden: recovery/image restore is a human operator action")
    if scenario in RESTORE_SCENARIOS:
        operator_recovery = config.get("operatorRecovery")
        _require(isinstance(operator_recovery, dict), "restore scenarios require operatorRecovery")
        _require(operator_recovery.get("mode") == "manual", "operatorRecovery.mode must be manual")
    return config


def _validate_mutation_spec(spec: Any, label: str, scenario: str, platform: str = "ec2") -> None:
    _require(isinstance(spec, dict), f"config.{label} must be an object")
    kind = spec.get("kind")
    _require(kind in MUTATION_KINDS, f"{label}.kind must be one of {sorted(MUTATION_KINDS)}")
    if scenario == "B-02":
        _require(kind == "b02-terminate", "B-02 T1 mutation must use the b02-terminate adapter")
    else:
        _require(kind in {"terraform-apply", "recovery-rollout"}, f"{scenario} mutations must use an approved rollout adapter")
    argv = spec.get("argv")
    _require(isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv), f"{label}.argv must be a string list")
    if kind == "b02-terminate":
        expected_adapter = (
            "actions/b02-eks-node-replacement.py"
            if platform == "eks"
            else "actions/b02-one-instance-replacement.py"
        )
        _require(
            argv[0].endswith(expected_adapter) or (
                argv[0] == "python3" and len(argv) > 1 and argv[1].endswith(expected_adapter)
            ),
            f"{label}.argv must invoke the platform-specific B-02 adapter",
        )
        _require("execute" in argv, f"{label}.argv must use the adapter execute mode")
        _require("--approval-file" in argv, f"{label}.argv must pass --approval-file")
    elif kind == "terraform-apply":
        _require(argv[0] == "terraform" and "apply" in argv, f"{label}.argv must be a terraform apply")
        _require("-auto-approve" not in argv, f"{label}.argv must not use -auto-approve")
        _require(isinstance(spec.get("planFile"), str) and spec["planFile"], f"{label}.planFile is required")
        _require(argv[-1] == spec["planFile"] or Path(argv[-1]).name == Path(spec["planFile"]).name, f"{label}.argv must apply the exact saved plan")
        _require(bool(SHA256_RE.fullmatch(str(spec.get("planSha256", "")))), f"{label}.planSha256 is required")
    else:
        _require(
            argv[0].endswith("actions/start-recovery-rollout.py") or (
                argv[0] == "python3" and len(argv) > 1 and argv[1].endswith("actions/start-recovery-rollout.py")
            ),
            f"{label}.argv must invoke the Recovery rollout adapter",
        )
        _require("execute" in argv and "--approval-file" in argv, f"{label}.argv must use execute with --approval-file")
        _require(isinstance(spec.get("planFile"), str) and spec["planFile"], f"{label}.planFile is required")
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
                "observations": [],
            }
            self._write()
        self._payload.setdefault("observations", [])

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

    def record_observation(self, stream: str, status: str, detail: dict[str, Any] | None = None) -> None:
        """Append a non-blocking platform observation.

        Platform events can legitimately be missed between polls. They are
        recorded as ``not_observed`` rather than creating a synthetic failed
        lifecycle step, so a skipped state cannot deadlock the run.
        """

        _require(status in {"observed", "not_observed", "terminal"}, "invalid observation status")
        self._payload["observations"].append({
            "stream": stream,
            "status": status,
            "recordedAtUtc": utc_iso(self._clock.now()),
            **({"detail": detail} if detail else {}),
        })
        self._write()

    @property
    def mutations(self) -> list[dict[str, Any]]:
        return list(self._payload["mutations"])

    @property
    def observations(self) -> list[dict[str, Any]]:
        return list(self._payload.get("observations", []))


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
        self.platform = str(config.get("platform", "ec2"))
        self._last_platform_snapshot: dict[str, Any] | None = None
        timing = config.get("timing", {})
        self.warmup_seconds = int(timing.get("warmupSeconds", 180))
        self.normal_window_seconds = int(timing.get("normalWindowSeconds", 120))
        self.poll_seconds = int(timing.get("pollSeconds", 20))
        self.detector_timeout_seconds = int(timing.get("detectorTimeoutSeconds", 900))
        self.run_end_timeout_seconds = int(timing.get("runEndTimeoutSeconds", 2400))
        self.minimum_window_ratio = float(timing.get("minimumWindowSuccessRatio", 0.9))
        self._operator_recovery_event: dict[str, Any] | None = None
        # Snapshot the EKS workload before T1.  ``updatedReplicas`` is a
        # steady-state field and is already non-zero for a healthy Deployment;
        # comparing it to zero would falsely call every normal run a node
        # replacement.  The baseline lets detectors identify an actual Pod or
        # node transition instead.
        self._eks_pre_t1_snapshot: dict[str, Any] | None = None

    # ----- runner helpers ---------------------------------------------------

    def _runner_shell(self, argv: Sequence[str], *, timeout_seconds: int, comment: str, background: bool = False) -> str:
        repo = self.config["runner"]["repositoryRoot"]
        quoted = " ".join(shlex.quote(item) for item in argv)
        command = f"cd {shlex.quote(repo)} && {quoted}"
        if background:
            # SSM Run Command tracks descendants in its execution cgroup. A
            # plain nohup/setsid child therefore keeps the invocation InProgress
            # until k6 exits and is killed at executionTimeout. systemd-run
            # creates a separate transient unit and --no-block returns after
            # handing off the workload; k6 still owns RUN_END/run-status and no
            # recovery action is automated here.
            unit_suffix = re.sub(r"[^A-Za-z0-9_.-]", "-", str(self.config["runId"]))
            unit = f"scrum43-recovery-{unit_suffix}"[:240]
            detached = shlex.quote(
                f"{quoted} >> {shlex.quote(self.config['runner']['runDir'])}/coordinator-workload.log 2>&1"
            )
            command = (
                f"systemd-run --unit={shlex.quote(unit)} --collect --no-block "
                f"--working-directory={shlex.quote(repo)} /bin/sh -c {detached} "
                f"> /dev/null 2>&1 && echo started:{shlex.quote(unit)}"
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

    def _read_operator_recovery_event(self) -> dict[str, Any] | None:
        """Read the operator's post-T3 recovery marker without mutating it.

        Recovery is intentionally a human decision.  A healthy target by
        itself is not enough to advance T4 because an ASG/EKS controller can
        become healthy again without the operator having cancelled the bad
        refresh or restored the known-good image.  The separate
        ``OPERATOR_RECOVERY`` event is therefore the explicit hand-off from
        the operator to this coordinator.
        """

        if self._operator_recovery_event is not None:
            return dict(self._operator_recovery_event)
        _require(self.state.is_done("t3"), "manual operator recovery requires a recorded T3")
        run_dir = self.config["runner"]["runDir"]
        output = self._runner_shell(
            [
                "sh",
                "-c",
                "if [ -f {path} ]; then tail -n 200 {path}; fi".format(
                    path=shlex.quote(run_dir + "/operations.jsonl")
                ),
            ],
            timeout_seconds=90,
            comment="operator-recovery-event",
        )
        t3_epoch = self.state.step_epoch("t3")
        for raw_line in output.splitlines():
            try:
                entry = json.loads(raw_line)
                if not isinstance(entry, dict):
                    continue
                event_time = datetime.fromisoformat(
                    str(entry.get("ts", "")).replace("Z", "+00:00")
                ).timestamp()
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if (
                entry.get("event") == "OPERATOR_RECOVERY"
                and entry.get("actor") == "operator"
                and event_time >= t3_epoch
            ):
                self._operator_recovery_event = {
                    "event": "OPERATOR_RECOVERY",
                    "actor": "operator",
                    "recordedAtUtc": utc_iso(event_time),
                }
                return dict(self._operator_recovery_event)
        return None

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
        if self.platform == "eks" and not self.config["target"].get("asgName"):
            return []
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
        if self.platform == "eks" and not self.config["target"].get("asgName"):
            payload = self.aws.call([
                "eks", "describe-nodegroup",
                "--cluster-name", self.config["target"]["clusterName"],
                "--nodegroup-name", self.config["target"]["nodeGroupName"],
            ])
            nodegroup = payload.get("nodegroup", {}) if isinstance(payload, dict) else {}
            status = nodegroup.get("status")
            update = nodegroup.get("updateConfig", {}) if isinstance(nodegroup, dict) else {}
            return [{"Status": status, "PercentageComplete": update.get("maxUnavailablePercentage", 0)}]
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

    def _eks_snapshot(self) -> dict[str, Any]:
        """Read a sanitized kubectl snapshot through the SSM bastion."""

        target = self.config["target"]
        cluster = target["clusterName"]
        node_group = target["nodeGroupName"]
        namespace = target.get("namespace", "travel-planner")
        deployment = target.get("deployment", "backend")
        region = self.config["region"]
        command = (
            "set -euo pipefail; "
            f"aws eks update-kubeconfig --name {shlex.quote(cluster)} --region {shlex.quote(region)} --alias scr43-eks; "
            f"printf '%s\\n' __SCRUM53_DEPLOYMENT_BEGIN__; kubectl --context scr43-eks -n {shlex.quote(namespace)} get deployment {shlex.quote(deployment)} -o json; printf '%s\\n' __SCRUM53_DEPLOYMENT_END__; "
            f"printf '%s\\n' __SCRUM53_PODS_BEGIN__; kubectl --context scr43-eks -n {shlex.quote(namespace)} get pods -l app.kubernetes.io/name=travel-planner-backend -o json; printf '%s\\n' __SCRUM53_PODS_END__; "
            f"printf '%s\\n' __SCRUM53_HPA_BEGIN__; kubectl --context scr43-eks -n {shlex.quote(namespace)} get hpa {shlex.quote(deployment)} -o json; printf '%s\\n' __SCRUM53_HPA_END__"
            f"; printf '%s\\n' __SCRUM53_NODES_BEGIN__; kubectl --context scr43-eks get nodes -o json; printf '%s\\n' __SCRUM53_NODES_END__"
            f"; printf '%s\\n' __SCRUM53_EVENTS_BEGIN__; kubectl --context scr43-eks get events --all-namespaces --sort-by=.lastTimestamp -o json; printf '%s\\n' __SCRUM53_EVENTS_END__"
        )
        stdout = self.ssm.run(command, timeout_seconds=180, comment="eks-platform-snapshot")
        snapshots: dict[str, Any] = {}
        for key in ("deployment", "pods", "hpa", "nodes", "events"):
            begin = f"__SCRUM53_{key.upper()}_BEGIN__"
            end = f"__SCRUM53_{key.upper()}_END__"
            match = re.search(re.escape(begin) + r"\s*(.*?)\s*" + re.escape(end), stdout, re.DOTALL)
            if not match:
                continue
            try:
                parsed = json.loads(match.group(1))
            except json.JSONDecodeError as error:
                raise CoordinatorError(f"EKS snapshot section {key} is not JSON") from error
            if isinstance(parsed, dict):
                snapshots[key] = parsed
        if not snapshots:
            self.state.record_observation("eks-platform-snapshot", "not_observed", {"reason": "no kubectl sections"})
        else:
            self.state.record_observation("eks-platform-snapshot", "observed", {"sections": sorted(snapshots)})
        merged = platform_high_watermark(self._last_platform_snapshot, snapshots)
        self._last_platform_snapshot = merged
        return merged

    def _eks_ready(self, snapshot: dict[str, Any]) -> bool:
        deployment = snapshot.get("deployment", {}) if isinstance(snapshot.get("deployment"), dict) else {}
        status = deployment.get("status", {}) if isinstance(deployment.get("status"), dict) else {}
        desired = int(status.get("replicas", 2) or 2)
        available = int(status.get("availableReplicas", 0) or 0)
        ready = int(status.get("readyReplicas", 0) or 0)
        return desired >= 2 and available >= 2 and ready >= 2

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
        if self.platform == "eks":
            self._eks_pre_t1_snapshot = self._eks_snapshot()
        self.log(f"[coordinator] pre-T1 normal window verified: successful={successful}")

    def _execute_mutation(self, label: str) -> None:
        spec = self.config[label]
        approval_path = Path(spec["approvalFile"])
        _require(approval_path.is_file(), f"{label} approval artifact is missing")
        _require(
            sha256_file(approval_path) == spec["approvalSha256"],
            f"{label} approval artifact digest changed; approval is void",
        )
        if spec["kind"] in {"terraform-apply", "recovery-rollout"}:
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
        if self.platform == "eks":
            def probe() -> str | None:
                snapshot = self._eks_snapshot()
                previous = self._eks_pre_t1_snapshot or {}
                previous_nodes = {
                    item.get("metadata", {}).get("name")
                    for item in (previous.get("nodes", {}).get("items", []) if isinstance(previous.get("nodes"), dict) else [])
                    if isinstance(item, dict)
                }
                current_nodes = {
                    item.get("metadata", {}).get("name")
                    for item in (snapshot.get("nodes", {}).get("items", []) if isinstance(snapshot.get("nodes"), dict) else [])
                    if isinstance(item, dict)
                }
                previous_pods = {
                    item.get("metadata", {}).get("name")
                    for item in (previous.get("pods", {}).get("items", []) if isinstance(previous.get("pods"), dict) else [])
                    if isinstance(item, dict)
                }
                current_pods = {
                    item.get("metadata", {}).get("name")
                    for item in (snapshot.get("pods", {}).get("items", []) if isinstance(snapshot.get("pods"), dict) else [])
                    if isinstance(item, dict)
                }
                if previous_nodes and current_nodes and current_nodes != previous_nodes:
                    return "EKS managed node membership changed after B-02"
                if previous_pods and current_pods and current_pods != previous_pods:
                    return "EKS backend Pod was rescheduled after B-02"
                for activity in self._scaling_activities():
                    description = str(activity.get("Description", ""))
                    if "Launching" in description or "Terminating" in description:
                        return "EKS managed-node ASG recorded a replacement activity"
                deployment = snapshot.get("deployment", {}) if isinstance(snapshot.get("deployment"), dict) else {}
                status = deployment.get("status", {}) if isinstance(deployment.get("status"), dict) else {}
                old_status = previous.get("deployment", {}).get("status", {}) if isinstance(previous.get("deployment"), dict) else {}
                if int(status.get("updatedReplicas", 0) or 0) > int(old_status.get("updatedReplicas", 0) or 0):
                    return "EKS Deployment observed an updated backend replica"
                return None
            return self._poll_until(f"{scenario} EKS first replacement", probe)
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
        if self.platform == "eks":
            def probe() -> str | None:
                snapshot = self._eks_snapshot()
                deployment = snapshot.get("deployment", {}) if isinstance(snapshot.get("deployment"), dict) else {}
                status = deployment.get("status", {}) if isinstance(deployment.get("status"), dict) else {}
                if not self._eks_ready(snapshot):
                    return "EKS Deployment/Pod readiness failure observed"
                health = self._target_health()
                if any(state in {"unhealthy", "initial", "draining"} for state in health.values()):
                    return "EKS ALB Pod-IP readiness failure observed"
                if int(status.get("updatedReplicas", 0) or 0) > 0 and int(status.get("availableReplicas", 0) or 0) < int(status.get("replicas", 2) or 2):
                    return "EKS rollout has updated but unavailable replicas"
                return None
            return self._poll_until(f"{scenario} EKS readiness failure", probe)
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
            self.state.record_observation("operator-recovery", "not_observed", {"mode": "manual"})

            def probe() -> str | None:
                operator_event = self._read_operator_recovery_event()
                if operator_event is None:
                    return None
                health = self._target_health()
                healthy = sum(state == "healthy" for state in health.values())
                if self.platform == "eks":
                    snapshot = self._eks_snapshot()
                    ready = self._eks_ready(snapshot)
                else:
                    ready = healthy >= int(self.config.get("expectedHealthyTargets", 2))
                if healthy >= int(self.config.get("expectedHealthyTargets", 2)) and ready:
                    self.state.record_observation(
                        "operator-recovery",
                        "observed",
                        {
                            "healthyTargets": healthy,
                            "event": operator_event,
                        },
                    )
                    return "human operator recovery observed; automation issued no restore mutation"
                return None

            return self._poll_until("manual operator recovery", probe)
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
            eks_ready = True
            if self.platform == "eks":
                eks_ready = self._eks_ready(self._eks_snapshot())
            if len(healthy) >= expected_healthy and not others and not (healthy & forbidden) and eks_ready:
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
        if self.platform == "eks":
            payload = self.aws.call([
                "eks", "describe-nodegroup",
                "--cluster-name", self.config["target"]["clusterName"],
                "--nodegroup-name", self.config["target"]["nodeGroupName"],
            ])
            nodegroup = payload.get("nodegroup", {}) if isinstance(payload, dict) else {}
            scaling = nodegroup.get("scalingConfig", {}) if isinstance(nodegroup, dict) else {}
            _require(
                (scaling.get("minSize"), scaling.get("desiredSize"), scaling.get("maxSize")) == (2, 2, 4),
                f"EKS node group capacity is not restored: {scaling}",
            )
            health = self._target_health()
            healthy = [target for target, state in health.items() if state == "healthy"]
            snapshot = self._eks_snapshot()
            _require(self._eks_ready(snapshot), "EKS Deployment is not ready during restoration read-back")
            _require(len(healthy) >= int(self.config.get("expectedHealthyTargets", 2)), "EKS healthy Pod target count is below the expected floor")
            readback = {
                "contractVersion": CONTRACT_VERSION,
                "runId": self.config["runId"],
                "scenario": self.config["scenario"],
                "platform": "eks",
                "capacity": {"minSize": scaling.get("minSize"), "desiredCapacity": scaling.get("desiredSize"), "maxSize": scaling.get("maxSize")},
                "healthyTargetCount": len(healthy),
                "deploymentReady": True,
                "mutationsExecuted": self.state.mutations,
                "recordedAtUtc": utc_iso(self.clock.now()),
            }
            control_dir = Path(self.config["controlDir"])
            control_dir.mkdir(parents=True, exist_ok=True)
            (control_dir / "restoration-readback.json").write_text(json.dumps(readback, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            self.log("[coordinator] EKS restoration read-back verified")
            return
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
    for label in ("t1Mutation",):
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
        "platform": config.get("platform", "ec2"),
        "steps": list(STEPS),
        "mutationChecks": checks,
        "mutations": [],
        "operatorRecovery": config.get("operatorRecovery", {"mode": "not-applicable"}),
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
