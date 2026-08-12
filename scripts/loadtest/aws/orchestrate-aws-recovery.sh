#!/usr/bin/env bash
# Common fail-closed AWS Recovery orchestrator.
#
# This script performs read-only target validation, starts the recovery k6
# workload, records sanitized operation events, and invokes the pure evidence
# evaluator. It deliberately contains no terminate, refresh, rollback, or
# Terraform command. Those destructive actions belong to separate scenario
# adapters and require their own approvals.
set -euo pipefail

MODE="preflight"
REPOSITORY_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PROFILE="$REPOSITORY_ROOT/load-tests/aws/profiles/ec2-recovery.json"
RUN_ID=""
REGION=""
ENVIRONMENT=""
EXPECTED_ACCOUNT_ID=""
ALB_ARN=""
ASG_NAME=""
LAUNCH_TEMPLATE_ID=""
LAUNCH_TEMPLATE_VERSION=""
RUNNER_ID=""
RUNNER_INSTANCE_TYPE="t3.small"
BASE_URL=""
RATE=""
K6_IMAGE=""
DATA_FILE=""
FREEZE_METADATA=""
D005_RATE_FILE=""
SOURCE_SHA=""
B01_PROFILE=""
BASELINE_CANDIDATE=""
OBSERVABILITY_STATUS=""
DRY_RUN=0
EVENT=""
EVENT_DETAIL=""

usage() {
  cat <<'USAGE'
usage: orchestrate-aws-recovery.sh <preflight|run|event|evaluate> [options]

Required for every mode:
  --run-id ID
  --profile PATH
  --region REGION
  --environment ENVIRONMENT
  --expected-account-id ID
  --alb-arn ARN             exact approved ALB ARN
  --asg-name NAME           exact approved backend ASG name
  --launch-template-id ID   exact approved backend Launch Template ID
  --launch-template-version VERSION exact numeric approved Launch Template version
  --runner-id INSTANCE_ID   exact standalone load-runner instance ID
  --base-url URL            approved custom HTTPS origin
  --rate RATE               exact D-005 frozen arrival rate
  --freeze-metadata PATH    D-006 metadata with sloVersion=v1.0-frozen
  --d005-rate-file PATH     D-005 record containing arrivalRate
  --b01-profile PATH        exact B-01 profile used for the D-005 record
  --baseline-candidate PATH exact baseline-candidate.json referenced by D-005
  --source-sha SHA          exact source commit SHA used by the Runner

Required for run:
  --k6-image IMAGE@sha256:DIGEST
  --data-file PATH          seeded credential file

Optional:
  --runner-instance-type TYPE  default: t3.small
  --observability-status PATH   defaults to <run-dir>/monitoring/required-metrics.json
  --event EVENT                 event mode: T0/T1/T2/T3/T4/T5
  --detail TEXT                 sanitized event detail (max 200 chars)
  --dry-run                     print AWS read-only calls; never contact AWS
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    preflight|run|event|evaluate) MODE="$1"; shift ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="$2"; shift 2 ;;
    --alb-arn) ALB_ARN="$2"; shift 2 ;;
    --asg-name) ASG_NAME="$2"; shift 2 ;;
    --launch-template-id) LAUNCH_TEMPLATE_ID="$2"; shift 2 ;;
    --launch-template-version) LAUNCH_TEMPLATE_VERSION="$2"; shift 2 ;;
    --runner-id) RUNNER_ID="$2"; shift 2 ;;
    --runner-instance-type) RUNNER_INSTANCE_TYPE="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --rate) RATE="$2"; shift 2 ;;
    --k6-image) K6_IMAGE="$2"; shift 2 ;;
    --data-file) DATA_FILE="$2"; shift 2 ;;
    --freeze-metadata) FREEZE_METADATA="$2"; shift 2 ;;
    --d005-rate-file) D005_RATE_FILE="$2"; shift 2 ;;
    --b01-profile) B01_PROFILE="$2"; shift 2 ;;
    --baseline-candidate) BASELINE_CANDIDATE="$2"; shift 2 ;;
    --source-sha) SOURCE_SHA="$2"; shift 2 ;;
    --observability-status) OBSERVABILITY_STATUS="$2"; shift 2 ;;
    --event) EVENT="$2"; shift 2 ;;
    --detail) EVENT_DETAIL="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for required in RUN_ID REGION ENVIRONMENT EXPECTED_ACCOUNT_ID ALB_ARN ASG_NAME LAUNCH_TEMPLATE_ID LAUNCH_TEMPLATE_VERSION RUNNER_ID BASE_URL RATE FREEZE_METADATA D005_RATE_FILE SOURCE_SHA B01_PROFILE BASELINE_CANDIDATE; do
  if [[ -z "${!required}" ]]; then
    echo "--${required,,} is required" >&2
    exit 2
  fi
done
if [[ ! "$RUN_ID" =~ ^aws-(recovery|b02|r01|r03|r05|r07)-[A-Za-z0-9._-]+$ ]]; then
  echo "--run-id must use an approved AWS Recovery prefix" >&2
  exit 2
fi
if [[ ! "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "--expected-account-id must be exactly 12 digits" >&2
  exit 2
fi
if [[ ! "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "--source-sha must be a 40-character lowercase commit SHA" >&2
  exit 2
fi
if [[ ! "$RUNNER_ID" =~ ^i-[0-9a-f]+$ ]]; then
  echo "--runner-id must be an EC2 instance ID" >&2
  exit 2
fi
if [[ ! "$BASE_URL" =~ ^https://[^/]+$ || "$BASE_URL" == *amazonaws.com* ]]; then
  echo "--base-url must be a custom HTTPS origin, not an AWS DNS name" >&2
  exit 2
fi
if [[ ! "$ASG_NAME" =~ ^[A-Za-z0-9._:/+=,@-]+$ ]]; then
  echo "--asg-name contains invalid characters" >&2
  exit 2
fi
if [[ ! "$LAUNCH_TEMPLATE_ID" =~ ^lt-[0-9a-f]+$ ]]; then
  echo "--launch-template-id must be an EC2 Launch Template ID" >&2
  exit 2
fi
if [[ ! "$LAUNCH_TEMPLATE_VERSION" =~ ^[0-9]+$ ]]; then
  echo '--launch-template-version must be an exact numeric version' >&2
  exit 2
fi
if [[ ! -f "$PROFILE" || ! -f "$B01_PROFILE" || ! -f "$FREEZE_METADATA" || ! -f "$D005_RATE_FILE" || ! -f "$BASELINE_CANDIDATE" ]]; then
  echo "Recovery/B-01 profiles, freeze metadata, D-005 rate, and baseline candidate must exist" >&2
  exit 2
fi
python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/validate-aws-recovery-profile.py" "$PROFILE"
if [[ "$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)" != "$SOURCE_SHA" ]]; then
  echo "repository HEAD does not match --source-sha" >&2
  exit 2
fi

RUN_DIR="$REPOSITORY_ROOT/evidence/aws-recovery/$RUN_ID"
mkdir -p "$RUN_DIR"
OBSERVABILITY_STATUS="${OBSERVABILITY_STATUS:-$RUN_DIR/monitoring/required-metrics.json}"

if [[ "$MODE" == "run" ]]; then
  for output in raw.json summary.json k6-native-summary.json run-status.json runner-stats.jsonl; do
    if [[ -e "$RUN_DIR/$output" ]]; then
      echo "refusing to reuse Recovery run with existing output: $RUN_DIR/$output" >&2
      exit 2
    fi
  done
fi

python3 - "$PROFILE" "$REGION" "$ENVIRONMENT" "$RATE" "$D005_RATE_FILE" "$FREEZE_METADATA" <<'PY'
import json
import math
import sys
from pathlib import Path

profile_path, region, environment, rate_raw, d005_path, freeze_path = sys.argv[1:]
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
if profile["region"] != region:
    raise SystemExit(f"--region {region} does not match profile region {profile['region']}")
if profile["environment"] != environment:
    raise SystemExit(f"--environment {environment} does not match profile environment {profile['environment']}")
try:
    rate = float(rate_raw)
    d005 = float(json.loads(Path(d005_path).read_text(encoding="utf-8"))["arrivalRate"])
except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
    raise SystemExit(f"invalid D-005 rate: {error}")
if not math.isfinite(rate) or rate <= 0 or not math.isclose(rate, d005, rel_tol=0, abs_tol=1e-9):
    raise SystemExit(f"--rate {rate_raw} does not exactly match D-005 arrivalRate {d005}")
freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
if freeze.get("sloVersion") != "v1.0-frozen" or not str(freeze.get("approvedBy", "")).strip():
    raise SystemExit("D-006 freeze metadata must be approved and have sloVersion=v1.0-frozen")
if not isinstance(freeze.get("runId"), str) or not freeze["runId"].strip():
    raise SystemExit("D-006 freeze metadata must include the B-01 runId")
if rate > profile["limits"]["maxRate"]:
    raise SystemExit("--rate exceeds Recovery profile limits.maxRate")
PY

python3 - "$D005_RATE_FILE" "$FREEZE_METADATA" "$B01_PROFILE" "$BASELINE_CANDIDATE" "$SOURCE_SHA" "$RATE" <<'PY'
import hashlib
import json
import math
import sys
from pathlib import Path

d005_path, freeze_path, b01_profile_path, candidate_path, source_sha, rate_raw = sys.argv[1:]
def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid JSON input: {path}: {error}")

d005 = read(d005_path)
freeze = read(freeze_path)
for field in ("runId", "sourceCommitSha", "profileSha256", "baselineCandidateSha256", "arrivalRate"):
    if field not in d005 or d005[field] in (None, ""):
        raise SystemExit(f"D-005 field is missing: {field}")
if d005["sourceCommitSha"] != source_sha:
    raise SystemExit("D-005 sourceCommitSha does not match --source-sha")
expected_b01_sha = hashlib.sha256(Path(b01_profile_path).read_bytes()).hexdigest()
if d005["profileSha256"] != expected_b01_sha:
    raise SystemExit("D-005 profileSha256 does not match --b01-profile")
candidate_sha = hashlib.sha256(Path(candidate_path).read_bytes()).hexdigest()
if d005["baselineCandidateSha256"] != candidate_sha:
    raise SystemExit("D-005 baselineCandidateSha256 does not match --baseline-candidate")
if freeze.get("sloVersion") != "v1.0-frozen" or not str(freeze.get("approvedBy", "")).strip():
    raise SystemExit("D-006 freeze metadata is not approved/v1.0-frozen")
if not isinstance(freeze.get("runId"), str) or not freeze["runId"].strip():
    raise SystemExit("D-006 freeze metadata must include the B-01 runId")
if freeze.get("runId") != d005.get("runId"):
    raise SystemExit("D-006 freeze runId does not match D-005 runId")
try:
    d005_rate = float(d005["arrivalRate"])
    requested_rate = float(rate_raw)
except (TypeError, ValueError) as error:
    raise SystemExit(f"invalid D-005 arrival rate: {error}")
if not math.isfinite(d005_rate) or d005_rate <= 0 or not math.isclose(d005_rate, requested_rate, rel_tol=0, abs_tol=1e-9):
    raise SystemExit("--rate does not exactly match D-005 arrivalRate")
PY

run_aws_json() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] aws $*" >&2
    echo '{}'
    return 0
  fi
  aws "$@"
}

target_preflight() {
  local account alb tags target_groups asg runner runner_tags target_group_arn target_health
  local preflight_output existing_preflight_outputs=0
  for preflight_output in metadata.json aws-alb.json aws-asg.json aws-target-health.json; do
    if [[ -e "$RUN_DIR/$preflight_output" ]]; then
      existing_preflight_outputs=$((existing_preflight_outputs + 1))
    fi
  done
  if [[ "$existing_preflight_outputs" -ne 0 && "$existing_preflight_outputs" -ne 4 ]]; then
    echo "refusing to reuse Recovery run with incomplete immutable preflight evidence; use a new --run-id" >&2
    exit 2
  fi

  account="$(run_aws_json sts get-caller-identity --region "$REGION" --query Account --output text 2>/dev/null || true)"
  if [[ "$DRY_RUN" != "1" && "$account" != "$EXPECTED_ACCOUNT_ID" ]]; then
    echo "observed AWS account does not match --expected-account-id" >&2
    exit 1
  fi

  alb="$(run_aws_json elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" --region "$REGION")"
  tags="$(run_aws_json elbv2 describe-tags --resource-arns "$ALB_ARN" --region "$REGION")"
  target_groups="$(run_aws_json elbv2 describe-target-groups --load-balancer-arn "$ALB_ARN" --region "$REGION")"
  asg="$(run_aws_json autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG_NAME" --region "$REGION")"
  runner="$(run_aws_json ec2 describe-instances --instance-ids "$RUNNER_ID" --region "$REGION")"
  runner_tags="$(run_aws_json ec2 describe-tags --filters "Name=resource-id,Values=$RUNNER_ID" "Name=resource-type,Values=instance" --region "$REGION")"

  if [[ "$DRY_RUN" != "1" ]]; then
    python3 - "$alb" "$tags" "$target_groups" "$asg" "$runner" "$runner_tags" \
      "$ALB_ARN" "$ASG_NAME" "$LAUNCH_TEMPLATE_ID" "$LAUNCH_TEMPLATE_VERSION" \
      "$RUNNER_ID" "$ENVIRONMENT" "$RUNNER_INSTANCE_TYPE" "$PROFILE" "$BASE_URL" <<'PY'
import json
import sys
from urllib.parse import urlparse

alb, tags, target_groups, asg, runner, runner_tags, alb_arn, asg_name, launch_template_id, launch_template_version, runner_id, environment, runner_type, profile_path, base_url = sys.argv[1:]
alb_payload = json.loads(alb)
load_balancers = alb_payload.get("LoadBalancers", [])
if len(load_balancers) != 1 or load_balancers[0].get("LoadBalancerArn") != alb_arn:
    raise SystemExit("ALB did not resolve to the exact approved ARN")
tag_descriptions = json.loads(tags).get("TagDescriptions", [])
alb_tags = {item.get("Key"): item.get("Value") for item in (tag_descriptions[0].get("Tags", []) if tag_descriptions else [])}
expected = json.loads(open(profile_path, encoding="utf-8").read())
for key, value in expected["target"]["expectedTags"].items():
    if alb_tags.get(key) != value:
        raise SystemExit(f"ALB tag {key} does not match approved environment")
groups = json.loads(target_groups).get("TargetGroups", [])
if len(groups) != 1:
    raise SystemExit("ALB must resolve to exactly one target group")
asg_items = json.loads(asg).get("AutoScalingGroups", [])
if len(asg_items) != 1 or asg_items[0].get("AutoScalingGroupName") != asg_name:
    raise SystemExit("ASG did not resolve to the exact approved name")
launch_template = asg_items[0].get("LaunchTemplate") or {}
if launch_template.get("LaunchTemplateId") != launch_template_id or str(launch_template.get("Version")) != launch_template_version:
    raise SystemExit("ASG Launch Template ID/version does not match approved inputs")
asg_tags = {item.get("Key"): item.get("Value") for item in asg_items[0].get("Tags", [])}
for key, value in expected["backend"]["expectedTags"].items():
    if asg_tags.get(key) != value:
        raise SystemExit(f"ASG tag {key} does not match approved value")
reservations = json.loads(runner).get("Reservations", [])
instances = [item for reservation in reservations for item in reservation.get("Instances", [])]
if len(instances) != 1 or instances[0].get("InstanceId") != runner_id:
    raise SystemExit("Runner did not resolve to the exact approved instance")
if instances[0].get("State", {}).get("Name") != "running":
    raise SystemExit("Runner EC2 is not running")
if instances[0].get("InstanceType") != runner_type:
    raise SystemExit("Runner EC2 instance type does not match approved input")
runner_tag_map = {item.get("Key"): item.get("Value") for item in json.loads(runner_tags).get("Tags", [])}
for key, value in expected["runner"]["expectedTags"].items():
    if runner_tag_map.get(key) != value:
        raise SystemExit(f"Runner tag {key} does not match approved value")
parsed = urlparse(base_url)
if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
    raise SystemExit("BASE_URL must be an origin-only HTTPS URL")
PY
    target_group_arn="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["TargetGroups"][0]["TargetGroupArn"])' <<<"$target_groups")"
    target_health="$(aws elbv2 describe-target-health --target-group-arn "$target_group_arn" --region "$REGION")"
    python3 - "$target_health" "$asg" <<'PY'
import json
import sys
health = json.loads(sys.argv[1]).get("TargetHealthDescriptions", [])
healthy = {item.get("Target", {}).get("Id") for item in health if item.get("TargetHealth", {}).get("State") == "healthy"}
if not healthy:
    raise SystemExit("approved ALB target group has no healthy backend target")
asg = json.loads(sys.argv[2]).get("AutoScalingGroups", [{}])[0]
asg_instances = {item.get("InstanceId") for item in asg.get("Instances", [])}
if not healthy.issubset(asg_instances):
    raise SystemExit("healthy ALB targets are not all members of the approved ASG")
PY
  else
    target_health='{"status":"dry-run"}'
  fi

  python3 - "$RUN_DIR/metadata.json" "$RUN_ID" "$PROFILE" "$B01_PROFILE" "$REGION" "$ENVIRONMENT" "$RATE" "$ALB_ARN" "$ASG_NAME" "$LAUNCH_TEMPLATE_ID" "$LAUNCH_TEMPLATE_VERSION" "$RUNNER_ID" "$BASE_URL" "$EXPECTED_ACCOUNT_ID" "$REPOSITORY_ROOT" "$existing_preflight_outputs" <<'PY'
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

output, run_id, profile_path, b01_profile_path, region, environment, rate, alb_arn, asg_name, launch_template_id, launch_template_version, runner_id, base_url, account_id, repo_root, existing_outputs_raw = sys.argv[1:]
profile_sha = hashlib.sha256(Path(profile_path).read_bytes()).hexdigest()
b01_profile_sha = hashlib.sha256(Path(b01_profile_path).read_bytes()).hexdigest()
commit_sha = subprocess.run(["git", "-C", repo_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
expected = {
    "runId": run_id,
    "scenarioId": "AWS-RECOVERY",
    "platform": "ec2",
    "environment": environment,
    "region": region,
    "commitSha": commit_sha,
    "profileSha256": profile_sha,
    "b01ProfileSha256": b01_profile_sha,
    "rate": float(rate),
    "sloVersion": "v1.0-frozen",
    "aws": {
        "accountIdLast4": account_id[-4:],
        "accountIdSha256": hashlib.sha256(account_id.encode()).hexdigest(),
        "accountValidation": "sts-observed-vs-operator-approved-runtime-input",
        "albArnHash": hashlib.sha256(alb_arn.encode()).hexdigest(),
        "autoScalingGroupName": asg_name,
        "launchTemplateId": launch_template_id,
        "launchTemplateVersion": launch_template_version,
        "runnerInstanceId": runner_id,
        "baseUrl": base_url,
    },
}
output_path = Path(output)
existing_outputs = int(existing_outputs_raw)
if existing_outputs:
    try:
        existing = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"immutable preflight metadata is invalid: {error}")
    if not isinstance(existing, dict):
        raise SystemExit("immutable preflight metadata must be a JSON object")
    for key, value in expected.items():
        if existing.get(key) != value:
            raise SystemExit(f"refusing to overwrite immutable preflight metadata: {key} does not match this run")
    if not isinstance(existing.get("startedAtUtc"), str) or not existing["startedAtUtc"].strip():
        raise SystemExit("immutable preflight metadata has no startedAtUtc")
    if existing.get("endedAtUtc") not in (None, ""):
        raise SystemExit("refusing to reuse a completed Recovery run; use a new --run-id")
else:
    payload = dict(expected)
    payload["startedAtUtc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload["endedAtUtc"] = None
    try:
        with output_path.open("x", encoding="utf-8") as output_file:
            output_file.write(json.dumps(payload, indent=2) + chr(10))
    except FileExistsError as error:
        raise SystemExit("immutable preflight metadata was created concurrently; retry with a new --run-id") from error
PY

  write_immutable_preflight_evidence() {
    local output="$1" content="$2"
    python3 - "$output" "$content" <<'PY'
import hashlib
import sys
from pathlib import Path

output, content = sys.argv[1:]
path = Path(output)
expected = (content + chr(10)).encode("utf-8")
if path.exists():
    try:
        actual = path.read_bytes()
    except OSError as error:
        raise SystemExit(f"cannot read immutable preflight evidence {path}: {error}")
    actual_sha = hashlib.sha256(actual).hexdigest()
    expected_sha = hashlib.sha256(expected).hexdigest()
    if actual_sha != expected_sha:
        raise SystemExit(
            f"refusing to overwrite immutable preflight evidence: {path} "
            f"(existing sha256={actual_sha}, expected sha256={expected_sha})"
        )
else:
    try:
        with path.open("xb") as output_file:
            output_file.write(expected)
    except FileExistsError as error:
        raise SystemExit(f"immutable preflight evidence was created concurrently: {path}") from error
PY
  }
  write_immutable_preflight_evidence "$RUN_DIR/aws-alb.json" "$alb"
  write_immutable_preflight_evidence "$RUN_DIR/aws-asg.json" "$asg"
  write_immutable_preflight_evidence "$RUN_DIR/aws-target-health.json" "$target_health"
  mkdir -p "$RUN_DIR/monitoring"
  if [[ "$DRY_RUN" != "1" && ! -f "$RUN_DIR/operations.jsonl" ]]; then
    python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_START "AWS Recovery preflight passed; workload may start" --actor automation
  fi
  echo "[recovery] preflight passed: run=$RUN_ID evidence=$RUN_DIR"
}
case "$MODE" in
  preflight)
    target_preflight
    ;;
  run)
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "[dry-run] would run AWS Recovery workload in $RUN_DIR"
      exit 0
    fi
    [[ -n "$K6_IMAGE" ]] || { echo "--k6-image is required for run" >&2; exit 2; }
    [[ -f "$DATA_FILE" ]] || { echo "--data-file must exist for run" >&2; exit 2; }
    target_preflight
    export REPOSITORY_ROOT BASE_URL RUN_ID REGION ENVIRONMENT RATE DATA_FILE
    export K6_IMAGE_DIGEST="$K6_IMAGE" AWS_RECOVERY_PROFILE_FILE="$PROFILE"
    export EFFECTIVE_MAX_VUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["recovery"]["maxVUs"])' "$PROFILE")"
    export RUN_DIR
    "$REPOSITORY_ROOT/scripts/loadtest/aws/run-aws-recovery-workload.sh" "$RUN_DIR"
    ;;
  event)
    [[ "$EVENT" =~ ^(T0|T1|T2|T3|T4|T5)$ ]] || { echo "--event must be one of T0/T1/T2/T3/T4/T5" >&2; exit 2; }
    [[ -f "$RUN_DIR/metadata.json" ]] || { echo "run has not passed preflight" >&2; exit 2; }
    newline="$(printf '\012')"
    if [[ "${#EVENT_DETAIL}" -gt 200 || "$EVENT_DETAIL" == *"$newline"* ]]; then
      echo "--detail must be a single line of at most 200 characters" >&2
      exit 2
    fi
    detail="$EVENT_DETAIL"
    [[ -n "$detail" ]] || detail="Recovery operator event"
    python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" "$EVENT" "$detail" --actor operator
    ;;
  evaluate)
    [[ -n "$K6_IMAGE" ]] || { echo "--k6-image is required for evaluate" >&2; exit 2; }
    evaluate_args=(
      "$RUN_DIR" --run-id "$RUN_ID" --profile "$PROFILE" --b01-profile "$B01_PROFILE"
      --freeze-metadata "$FREEZE_METADATA" --d005-rate-file "$D005_RATE_FILE"
      --baseline-candidate "$BASELINE_CANDIDATE" --rate "$RATE" --source-sha "$SOURCE_SHA"
    )
    evaluate_args+=(--k6-image "$K6_IMAGE")
    python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/evaluate-aws-recovery.py" "${evaluate_args[@]}"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
