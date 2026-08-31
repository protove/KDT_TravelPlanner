#!/usr/bin/env python3
"""Start one approved Recovery rollout without owning its later lifecycle.

The action is a small boundary adapter for the exact Terraform plan prepared
by the operator.  ``plan`` validates the saved plan and approval inputs but
does not contact Terraform.  ``execute`` applies that one plan, records only
its digest-bound receipt, and returns.  Observation, timing and any later
operator decision remain with the Recovery coordinator.
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
from typing import Any, Mapping, NamedTuple, Sequence


CONTRACT_VERSION = "aws-recovery-rollout-action-v1"
RUN_ID_PATTERN = re.compile(r"^(?:aws|scrum43)-(?:r01|r03|r05|r07)-[A-Za-z0-9._-]{1,80}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
APPROVED_PLATFORMS = {"ec2", "eks"}
APPROVED_ENVIRONMENTS = {"dev-runtime", "dev-eks"}
FORBIDDEN_APPROVER = re.compile(r"(?:AKIA|ASIA|aws_secret|password|token|secret|[0-9]{12})", re.I)


class RecoveryRolloutError(RuntimeError):
    """A sanitized rollout contract failure."""


class RolloutRequest(NamedTuple):
    run_id: str
    scenario: str
    platform: str
    environment: str
    region: str
    plan_file: Path
    approval_file: Path
    evidence_root: Path
    terraform_root: Path


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryRolloutError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_request(request: RolloutRequest) -> str:
    _require(RUN_ID_PATTERN.fullmatch(request.run_id) is not None, "--run-id must use an approved Recovery prefix")
    _require(request.scenario in {"R-01", "R-03", "R-05", "R-07"}, "--scenario is not an approved Recovery rollout")
    _require(request.platform in APPROVED_PLATFORMS, "--platform must be ec2 or eks")
    _require(request.environment in APPROVED_ENVIRONMENTS, "--environment is outside the disposable Recovery boundary")
    _require(re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z0-9-]+-[0-9]", request.region) is not None, "--region is invalid")
    _require(request.plan_file.is_file() and not request.plan_file.is_symlink(), "saved Terraform plan is missing")
    _require(request.approval_file.is_file() and not request.approval_file.is_symlink(), "approval file is missing")
    _require(not request.evidence_root.exists() or request.evidence_root.is_dir(), "--evidence-root must be a directory")
    _require(request.terraform_root.is_dir(), "--terraform-root must be a directory")
    plan_sha = _sha256(request.plan_file)
    _require(bool(SHA256_PATTERN.fullmatch(plan_sha)), "saved Terraform plan digest could not be computed")
    return plan_sha


def read_approval(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryRolloutError("approval file is not valid JSON") from error
    _require(isinstance(payload, Mapping) and payload.get("approved") is True, "Recovery rollout approval is not granted")
    approver = str(payload.get("approvedBy", ""))
    _require(approver and not FORBIDDEN_APPROVER.search(approver), "approval approver contains a forbidden credential or account value")
    return dict(payload), _sha256(path)


def build_receipt(request: RolloutRequest, plan_sha: str, *, mode: str, approval: Mapping[str, Any] | None = None, approval_sha: str | None = None, response_code: int | None = None) -> dict[str, Any]:
    return {
        "contractVersion": CONTRACT_VERSION,
        "runId": request.run_id,
        "scenario": request.scenario,
        "platform": request.platform,
        "environment": request.environment,
        "region": request.region,
        "mode": mode,
        "planSha256": plan_sha,
        "approval": ({"approved": True, "approvedBy": str(approval.get("approvedBy")), "sha256": approval_sha} if approval else None),
        "mutation": {
            "operation": "terraform-apply-saved-plan",
            "allowed": mode == "execute",
            "performed": mode == "execute" and response_code == 0,
            "responseCode": response_code,
        },
        "operatorBoundary": {
            "postActionDecisions": "operator-owned",
            "controllerOwns": ["timing", "observation", "evidence"],
        },
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def run_action(request: RolloutRequest, *, mode: str, terraform: Sequence[str] | None = None) -> dict[str, Any]:
    _require(mode in {"plan", "execute"}, "mode must be plan or execute")
    plan_sha = validate_request(request)
    approval_payload = None
    approval_sha = None
    response_code = None
    if mode == "execute":
        approval_payload, approval_sha = read_approval(request.approval_file)
        command = list(terraform or ("terraform", "apply", str(request.plan_file)))
        _require(command[:2] == ["terraform", "apply"], "rollout command must be terraform apply")
        _require("-auto-approve" not in command, "rollout command must not use -auto-approve")
        _require(Path(command[-1]).resolve() == request.plan_file.resolve(), "rollout command must apply the exact saved plan")
        completed = subprocess.run(command, cwd=request.terraform_root, capture_output=True, text=True, check=False)
        response_code = completed.returncode
        _require(response_code == 0, "saved Recovery rollout plan failed")
    result = build_receipt(request, plan_sha, mode=mode, approval=approval_payload, approval_sha=approval_sha, response_code=response_code)
    request.evidence_root.mkdir(parents=True, exist_ok=True)
    output = request.evidence_root / "recovery-rollout-action.json"
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if output.exists():
        _require(output.read_text(encoding="utf-8") == encoded, "existing rollout receipt differs; refusing overwrite")
    else:
        with output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "execute"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--terraform-root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    request = RolloutRequest(
        args.run_id, args.scenario, args.platform, args.environment, args.region,
        args.plan_file.resolve(), args.approval_file.resolve(), args.evidence_root.resolve(), args.terraform_root.resolve(),
    )
    result = run_action(request, mode=args.mode)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecoveryRolloutError as error:
        print(f"[recovery-rollout] blocked: {error}", file=sys.stderr)
        raise SystemExit(2)
