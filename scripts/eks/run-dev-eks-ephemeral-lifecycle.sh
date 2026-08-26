#!/usr/bin/env bash
set -euo pipefail

# Disposable dev-eks lifecycle coordinator.  It resumes the already-created
# Terraform layer, gates Kubernetes with the real render hash, and arms an
# idempotent cleanup finalizer before any Kubernetes mutation.
umask 077

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TERRAFORM_ROOT="$SCRIPT_ROOT/infra/environments/dev-eks"
PERSISTENT_TERRAFORM_ROOT="$SCRIPT_ROOT/infra/environments/dev"
DEPLOY_SCRIPT="$SCRIPT_ROOT/scripts/eks/deploy-dev-eks.sh"
REMOTE_HELPER="$SCRIPT_ROOT/scripts/eks/run-dev-eks-lifecycle-remote.sh"
DESTROY_VERIFIER="$SCRIPT_ROOT/scripts/eks/verify-dev-eks-destroyed.py"
SMOKE_SCRIPT="$SCRIPT_ROOT/monitoring/verify-eks-observability-smoke.py"

AWS_PROFILE=""
REGION="ap-northeast-2"
EXPECTED_ACCOUNT_ID=""
BACKEND_IMAGE=""
BACKEND_HOSTNAME=""
FRONTEND_ORIGIN=""
AUTONOMOUS=false
CANONICAL_PROFILE="kdt-travel-terraform"
CANONICAL_REGION="ap-northeast-2"
CANONICAL_INPUT_JSON="$SCRIPT_ROOT/evidence/eks-deploy/20260824T133440Z-15798/action-values.json"
CANONICAL_INPUT_SHA256="3c0a636a230247a10c785822487df1ca8b5a1cfeead4d695f54afdc98d4f44f8"
RESUME_RUN_ID="20260824T133440Z-15798"
# v15 keeps the retained environment bounded even when the current SSO role
# has a shorter remaining session.  bootstrap_ephemeral_credentials() below
# tightens this window to the actual credential horizon before any mutation.
LIFECYCLE_DEADLINE_SECONDS="2400"
CLEANUP_RESERVE_SECONDS="600"
SSM_TIMEOUT_SECONDS="1800"
INPUT_JSON=""
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"

PLAN_VERSION=15
PLAN_MANIFEST_SHA256="9171c3c0153e8a5ce50e64796b8215ba55c63401c45a394110f8b7beb378c5ab"
PLAN_HANDOFF_PATH="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v15.yaml"
PLAN_HANDOFF_SHA256="c2d0a19130d430a2d3d9a9e3ce14e6bd4c1a5bda0812cf128923c1464880d69d"

REPORT_ROOT="$SCRIPT_ROOT/evidence/eks-lifecycle/$RUN_ID"
LOG_FILE="$REPORT_ROOT/orchestrator.log"
LEASE_FILE="$REPORT_ROOT/cleanup-lease.json"
LEASE_HASH_FILE="$REPORT_ROOT/cleanup-lease.sha256"
STATE_FILE="$REPORT_ROOT/state-before.private.json"
ADDRESSES_FILE="$REPORT_ROOT/managed-addresses.private.txt"
PROTECTED_STATE_FILE="$REPORT_ROOT/protected-dev-state-before.private.json"
PROTECTED_STATES_FILE="$REPORT_ROOT/protected-states-before.private.json"
PROTECTED_STATES_AFTER_FILE="$REPORT_ROOT/protected-states-after.private.json"
DESTROY_PLAN="$REPORT_ROOT/destroy.tfplan"
DESTROY_PLAN_JSON="$REPORT_ROOT/destroy-plan.private.json"
DESTROY_PREVIEW_PLAN="$REPORT_ROOT/destroy-preview.tfplan"
DESTROY_PREVIEW_PLAN_JSON="$REPORT_ROOT/destroy-preview-plan.private.json"
FINAL_SUMMARY="$REPORT_ROOT/final-summary.json"
AUTHORIZATION_RECEIPT="$REPORT_ROOT/authorization-receipt.private.json"
AUTHORIZATION_RECEIPT_SHA256_FILE="$REPORT_ROOT/authorization-receipt.sha256"
DEADLINE_MARKER="$REPORT_ROOT/deadline.expired"
HELPER_KEY=""
HELPER_SHA256=""
SMOKE_SCRIPT_KEY=""
SMOKE_SCRIPT_SHA256=""
MONITORING_BUCKET=""
MONITORING_PREFIX=""
BUNDLE_REVISION=""
MONITORING_DNS=""
DATABASE_IDENTIFIER=""
REDIS_REPLICATION_GROUP_ID=""
REDIS_ENDPOINT=""
REDIS_PORT=""
REDIS_SECRET_ARN=""
PROFILE_IMAGE_BUCKET=""
PROFILE_IMAGE_BASE_URL=""
OPERATOR_DATA_KEY=""
OPERATOR_DATA_SHA256=""
OPERATOR_DATA_FILE="$REPORT_ROOT/operator-data-evidence.private.json"
INGRESS_CNAME_TARGET=""
PARAMETER_NAME=""
BASTION_ID=""
CLUSTER_NAME=""
TERRAFORM_VPC_ID=""
TERRAFORM_PUBLIC_SUBNET_IDS=""
TERRAFORM_CERTIFICATE_ARN=""

LEASE_ACCEPTED=false
CLEANUP_STARTED=false
CLEANUP_RESULT="not_started"
VERIFICATION_RESULT="not_started"
FULL_SUCCESS_EVIDENCE_FROZEN=false
DESTROY_ARMED=false
PRECONDITION_MODE="unknown"
REMOTE_CLEANUP_RESULT="not_started"
DESTROY_RESULT="not_started"
FINAL_EXIT=0
WATCHDOG_PID=""
ACTIVE_CHILD_PID=""
DEADLINE_EXPIRED=false
KEEP_AWAKE_PID=""
AUTHORIZATION_RECEIPT_SHA256=""
SSM_TRANSPORT_DENIED=false
CAPSULE_SHA256=""
CAPSULE_VPC_ID=""
CAPSULE_PUBLIC_SUBNET_IDS=""
CAPSULE_CERTIFICATE_ARN=""
CAPSULE_BACKEND_ORIGIN=""
CAPSULE_BACKEND_IMAGE=""
CAPSULE_BACKEND_HOSTNAME=""
CAPSULE_FRONTEND_ORIGIN=""
STATE_SHA256=""
ADDRESS_SHA256=""
ADDRESS_COUNT="0"
STATE_LINEAGE=""
STATE_SERIAL="0"
BOOTSTRAPPED_EPHEMERAL_CREDENTIALS=false
AWS_CREDENTIAL_EXPIRATION=""

mkdir -p "$REPORT_ROOT"
chmod 0700 "$REPORT_ROOT"

log_event() {
  printf 'phase=%s status=%s\n' "$1" "$2" >>"$LOG_FILE"
}

die() {
  printf 'status=failed reason=%s\n' "$1" >&2
  exit 1
}

usage() {
  cat >&2 <<'USAGE'
Usage: run-dev-eks-ephemeral-lifecycle.sh \
  --aws-profile <profile> --region ap-northeast-2 --expected-account-id <12 digits> \
  --backend-image <repository-uri>@sha256:<64 lowercase hex> \
  --backend-hostname <lowercase DNS hostname> \
  --frontend-origin <https origin without path/query/fragment> \
  [--resume-run-id <previous-run-id>] \
  [--lifecycle-deadline-seconds <integer>] [--cleanup-reserve-seconds <integer>] \
  [--input-json <mode-0600 strict JSON capsule>]

Autonomous executor mode:
  run-dev-eks-ephemeral-lifecycle.sh --autonomous

The lifecycle never accepts Terraform create-plan arguments and never pauses
for a typed approval.  The explicit v15 authorization is bound internally to
the immutable handoff, State fingerprints and render hash; the cleanup lease
is created and consumed internally by the same bounded execution.
USAGE
}

load_autonomous_capsule() {
  local capsule="$CANONICAL_INPUT_JSON" actual image_registry
  command -v jq >/dev/null 2>&1 || die "required command unavailable: jq"
  command -v sha256sum >/dev/null 2>&1 || die "required command unavailable: sha256sum"
  [[ -f "$capsule" && ! -L "$capsule" ]] || die "canonical action-values capsule is unavailable"
  [[ "$(stat -f '%Lp' "$capsule" 2>/dev/null || stat -c '%a' "$capsule" 2>/dev/null)" == "600" ]] || die "canonical action-values capsule must have mode 0600"
  actual="$(sha256sum "$capsule" | awk '{print $1}')"
  [[ "$actual" == "$CANONICAL_INPUT_SHA256" ]] || die "canonical action-values capsule sha256 does not match the v15 contract"
  jq -e 'type == "object" and (keys | sort) == ["api_certificate_arn","backend_hostname","backend_image","backend_origin","frontend_origin","public_subnet_ids","vpc_id"] and (.public_subnet_ids | type == "array" and length > 0 and all(.[]; type == "string"))' "$capsule" >/dev/null || die "canonical action-values capsule schema is invalid"
  AWS_PROFILE="$CANONICAL_PROFILE"
  REGION="$CANONICAL_REGION"
  CAPSULE_SHA256="$actual"
  CAPSULE_VPC_ID="$(jq -er '.vpc_id | select(type == "string" and test("^vpc-[0-9a-f]+$"))' "$capsule")" || die "canonical capsule VPC is invalid"
  CAPSULE_PUBLIC_SUBNET_IDS="$(jq -cS '.public_subnet_ids' "$capsule")" || die "canonical capsule subnets are invalid"
  CAPSULE_CERTIFICATE_ARN="$(jq -er '.api_certificate_arn | select(type == "string" and test("^arn:aws:acm:ap-northeast-2:[0-9]{12}:certificate/[0-9a-f-]+$"))' "$capsule")" || die "canonical capsule ACM certificate is invalid"
  CAPSULE_BACKEND_HOSTNAME="$(jq -er '.backend_hostname | select(type == "string")' "$capsule")" || die "canonical capsule backend hostname is missing"
  CAPSULE_BACKEND_ORIGIN="$(jq -er '.backend_origin | select(type == "string")' "$capsule")" || die "canonical capsule backend origin is missing"
  CAPSULE_BACKEND_IMAGE="$(jq -er '.backend_image | select(type == "string")' "$capsule")" || die "canonical capsule backend image is missing"
  CAPSULE_FRONTEND_ORIGIN="$(jq -er '.frontend_origin | select(type == "string")' "$capsule")" || die "canonical capsule frontend origin is missing"
  [[ "$CAPSULE_BACKEND_ORIGIN" == "https://$CAPSULE_BACKEND_HOSTNAME" ]] || die "canonical capsule backend origin does not match hostname"
  [[ "$CAPSULE_BACKEND_IMAGE" =~ ^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || die "canonical capsule backend image is invalid"
  image_registry="${BASH_REMATCH[1]}"
  [[ "${BASH_REMATCH[2]}" == "$REGION" ]] || die "canonical capsule backend image region does not match"
  EXPECTED_ACCOUNT_ID="$image_registry"
  BACKEND_IMAGE="$CAPSULE_BACKEND_IMAGE"
  BACKEND_HOSTNAME="$CAPSULE_BACKEND_HOSTNAME"
  FRONTEND_ORIGIN="$CAPSULE_FRONTEND_ORIGIN"
  RESUME_RUN_ID="20260824T133440Z-15798"
  LIFECYCLE_DEADLINE_SECONDS="2400"
  CLEANUP_RESERVE_SECONDS="600"
  SSM_TIMEOUT_SECONDS="1800"
  INPUT_JSON="$capsule"
}

while (($#)); do
  case "$1" in
    --autonomous) AUTONOMOUS=true; shift ;;
    --aws-profile) AWS_PROFILE="${2:?missing value for --aws-profile}"; shift 2 ;;
    --region) REGION="${2:?missing value for --region}"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="${2:?missing value for --expected-account-id}"; shift 2 ;;
    --backend-image) BACKEND_IMAGE="${2:?missing value for --backend-image}"; shift 2 ;;
    --backend-hostname) BACKEND_HOSTNAME="${2:?missing value for --backend-hostname}"; shift 2 ;;
    --frontend-origin) FRONTEND_ORIGIN="${2:?missing value for --frontend-origin}"; shift 2 ;;
    --resume-run-id) RESUME_RUN_ID="${2:?missing value for --resume-run-id}"; shift 2 ;;
    --lifecycle-deadline-seconds) LIFECYCLE_DEADLINE_SECONDS="${2:?missing value for --lifecycle-deadline-seconds}"; shift 2 ;;
    --cleanup-reserve-seconds) CLEANUP_RESERVE_SECONDS="${2:?missing value for --cleanup-reserve-seconds}"; shift 2 ;;
    --input-json) INPUT_JSON="${2:?missing value for --input-json}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument" ;;
  esac
done

if [[ "$AUTONOMOUS" == true ]]; then
  load_autonomous_capsule
else
  SSM_TIMEOUT_SECONDS="${DEV_EKS_SSM_TIMEOUT_SECONDS:-1800}"
fi

[[ "$REGION" == "ap-northeast-2" ]] || die "region must be ap-northeast-2 for this dev contract"
[[ "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || die "expected account id must be 12 digits"
[[ "$BACKEND_IMAGE" =~ ^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || die "backend image must be an ECR URI with a lowercase sha256 digest"
[[ "$BACKEND_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "backend hostname must be a lowercase DNS hostname"
[[ "$FRONTEND_ORIGIN" =~ ^https://[a-z0-9.-]+$ ]] || die "frontend origin must be a simple https origin"
[[ "$RESUME_RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || die "resume run id has an invalid shape"
[[ "$LIFECYCLE_DEADLINE_SECONDS" =~ ^[0-9]+$ && "$LIFECYCLE_DEADLINE_SECONDS" -ge 300 && "$LIFECYCLE_DEADLINE_SECONDS" -le 86400 ]] || die "lifecycle deadline must be between 300 and 86400 seconds"
[[ "$CLEANUP_RESERVE_SECONDS" =~ ^[0-9]+$ && "$CLEANUP_RESERVE_SECONDS" -ge 300 && "$CLEANUP_RESERVE_SECONDS" -le 86400 ]] || die "cleanup reserve must be between 300 and 86400 seconds"
[[ "$SSM_TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$SSM_TIMEOUT_SECONDS" -le 7200 ]] || die "SSM timeout must be an integer between 0 and 7200 seconds"

for command_name in aws jq sha256sum terraform python3 mktemp; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
done
[[ -x "$DEPLOY_SCRIPT" ]] || die "deployment operator script is unavailable"
[[ -f "$REMOTE_HELPER" ]] || die "remote lifecycle helper is unavailable"
[[ -f "$DESTROY_VERIFIER" ]] || die "destroy verifier is unavailable"
[[ -f "$SMOKE_SCRIPT" ]] || die "observability smoke verifier is unavailable"

aws_args=(--profile "$AWS_PROFILE" --region "$REGION")
[[ -n "$AWS_PROFILE" ]] || die "aws profile is required"

if [[ -n "$INPUT_JSON" && "$AUTONOMOUS" != true ]]; then
  [[ -f "$INPUT_JSON" && ! -L "$INPUT_JSON" ]] || die "input JSON must be a regular file"
  [[ "$(stat -f '%Lp' "$INPUT_JSON" 2>/dev/null || stat -c '%a' "$INPUT_JSON" 2>/dev/null)" == "600" ]] || die "input JSON must have mode 0600"
  jq -e 'type == "object" and ([keys[] | select(. as $k | ["aws_profile","region","expected_account_id","backend_image","backend_hostname","frontend_origin"] | index($k) | not)] | length == 0)' "$INPUT_JSON" >/dev/null || die "input JSON schema is invalid"
  INPUT_AWS_PROFILE="$(jq -er '.aws_profile // empty' "$INPUT_JSON")" || die "input JSON aws_profile is missing"
  INPUT_REGION="$(jq -er '.region // empty' "$INPUT_JSON")" || die "input JSON region is missing"
  INPUT_ACCOUNT="$(jq -er '.expected_account_id // empty' "$INPUT_JSON")" || die "input JSON account is missing"
  INPUT_IMAGE="$(jq -er '.backend_image // empty' "$INPUT_JSON")" || die "input JSON image is missing"
  INPUT_HOST="$(jq -er '.backend_hostname // empty' "$INPUT_JSON")" || die "input JSON hostname is missing"
  INPUT_ORIGIN="$(jq -er '.frontend_origin // empty' "$INPUT_JSON")" || die "input JSON origin is missing"
  [[ "$INPUT_AWS_PROFILE" == "$AWS_PROFILE" && "$INPUT_REGION" == "$REGION" && "$INPUT_ACCOUNT" == "$EXPECTED_ACCOUNT_ID" && "$INPUT_IMAGE" == "$BACKEND_IMAGE" && "$INPUT_HOST" == "$BACKEND_HOSTNAME" && "$INPUT_ORIGIN" == "$FRONTEND_ORIGIN" ]] || die "input JSON does not match explicit CLI inputs"
fi

load_runtime_outputs() {
  local outputs
  outputs="$(terraform_with_auth -chdir="$TERRAFORM_ROOT" output -json 2>>"$LOG_FILE")" || die "dev-eks Terraform outputs could not be read"
  TERRAFORM_VPC_ID="$(jq -er '.vpc_id.value | select(type == "string")' <<<"$outputs")" || die "VPC output is missing"
  TERRAFORM_PUBLIC_SUBNET_IDS="$(jq -cjS '.public_subnet_ids.value | select(type == "array")' <<<"$outputs")" || die "public subnet output is missing"
  TERRAFORM_CERTIFICATE_ARN="$(jq -er '.api_certificate_arn.value | select(type == "string")' <<<"$outputs")" || die "ACM certificate output is missing"
  MONITORING_BUCKET="$(jq -er '.monitoring_config_bucket_name.value | select(type == "string")' <<<"$outputs")" || die "monitoring bucket output is missing"
  MONITORING_PREFIX="$(jq -er '.monitoring_bundle_prefix.value | select(type == "string")' <<<"$outputs")" || die "monitoring prefix output is missing"
  BUNDLE_REVISION="$(jq -er '.monitoring_bundle_revision.value | select(type == "string" and test("^[0-9a-f]{64}$"))' <<<"$outputs")" || die "monitoring bundle revision output is missing"
  MONITORING_DNS="$(jq -er '.monitoring_private_dns_name.value | select(type == "string")' <<<"$outputs")" || die "monitoring DNS output is missing"
  DATABASE_IDENTIFIER="$(jq -er '.database_identifier.value | select(type == "string")' <<<"$outputs")" || die "database identifier output is missing"
  REDIS_REPLICATION_GROUP_ID="$(jq -er '.redis_replication_group_id.value | select(type == "string")' <<<"$outputs")" || die "Redis replication group output is missing"
  REDIS_ENDPOINT="$(jq -er '.redis_primary_endpoint.value | select(type == "string")' <<<"$outputs")" || die "Redis endpoint output is missing"
  REDIS_PORT="$(jq -er '.redis_port.value | select(type == "number" or type == "string") | tostring' <<<"$outputs")" || die "Redis port output is missing"
  REDIS_SECRET_ARN="$(jq -er '.redis_auth_secret_arn.value | select(type == "string")' <<<"$outputs")" || die "Redis auth secret output is missing"
  PROFILE_IMAGE_BUCKET="$(jq -er '.profile_image_bucket_name.value | select(type == "string")' <<<"$outputs")" || die "profile-image bucket output is missing"
  PROFILE_IMAGE_BASE_URL="$(jq -er '.profile_image_public_base_url.value | select(type == "string")' <<<"$outputs")" || die "profile-image base URL output is missing"
  PARAMETER_NAME="$(jq -er '.monitoring_endpoint_parameter_name.value | select(type == "string")' <<<"$outputs")" || die "monitoring endpoint parameter output is missing"
  BASTION_ID="$(jq -er '.bastion_instance_id.value | select(type == "string")' <<<"$outputs")" || die "Bastion output is missing"
  CLUSTER_NAME="$(jq -er '.cluster_name.value | select(type == "string")' <<<"$outputs")" || die "cluster output is missing"
  [[ "$MONITORING_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die "monitoring bucket output is invalid"
  [[ "$MONITORING_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$ && "$MONITORING_PREFIX" != *".."* && "$MONITORING_PREFIX" != *"//"* ]] || die "monitoring prefix output is invalid"
  [[ "$BASTION_ID" =~ ^i-[0-9a-f]+$ ]] || die "Bastion output is invalid"
  [[ "$CLUSTER_NAME" =~ ^[a-z0-9][a-z0-9-]{0,99}$ ]] || die "cluster output is invalid"
  [[ "$REDIS_ENDPOINT" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "Redis endpoint output is invalid"
  [[ "$REDIS_PORT" =~ ^[0-9]+$ && "$REDIS_PORT" -ge 1 && "$REDIS_PORT" -le 65535 ]] || die "Redis port output is invalid"
  [[ "$REDIS_SECRET_ARN" =~ ^arn:aws:secretsmanager:${REGION}:${EXPECTED_ACCOUNT_ID}:secret:.+$ ]] || die "Redis secret output is invalid"
  HELPER_KEY="$MONITORING_PREFIX/runs/$RUN_ID/lifecycle/run-dev-eks-lifecycle-remote.sh"
  SMOKE_SCRIPT_KEY="$MONITORING_PREFIX/runs/$RUN_ID/lifecycle/verify-eks-observability-smoke.py"
  OPERATOR_DATA_KEY="$MONITORING_PREFIX/runs/$RUN_ID/lifecycle/operator-data-evidence.json"
}

validate_capsule_against_outputs() {
  [[ "$AUTONOMOUS" == true ]] || return 0
  [[ "$TERRAFORM_VPC_ID" == "$CAPSULE_VPC_ID" ]] || die "canonical capsule VPC does not match dev-eks Terraform output"
  [[ "$TERRAFORM_PUBLIC_SUBNET_IDS" == "$CAPSULE_PUBLIC_SUBNET_IDS" ]] || die "canonical capsule public subnets do not match dev-eks Terraform output"
  [[ "$TERRAFORM_CERTIFICATE_ARN" == "$CAPSULE_CERTIFICATE_ARN" ]] || die "canonical capsule ACM certificate does not match dev-eks Terraform output"
  log_event "capsule_crosscheck" "passed"
}

verify_identity_and_protected_states() {
  local account state_output
  account="$(aws "${aws_args[@]}" sts get-caller-identity --query Account --output text 2>>"$LOG_FILE")" || die "AWS identity lookup failed"
  [[ "$account" == "$EXPECTED_ACCOUNT_ID" ]] || die "AWS account does not match expected account"
  for state_root in dev-runtime dev-load-test; do
    state_output="$(terraform_with_auth -chdir="$SCRIPT_ROOT/infra/environments/$state_root" state list 2>>"$LOG_FILE")" || die "$state_root State could not be read"
    [[ -z "$state_output" ]] || die "$state_root State is not empty; protected ownership precondition failed"
  done
}

verify_bastion_identity() {
  local details
  details="$(aws "${aws_args[@]}" ec2 describe-instances --instance-ids "$BASTION_ID" --output json 2>>"$LOG_FILE")" || die "Bastion identity lookup failed"
  jq -e --arg id "$BASTION_ID" '
    ([.Reservations[]?.Instances[]?] | length == 1) and
    .Reservations[0].Instances[0].InstanceId == $id and
    .Reservations[0].Instances[0].State.Name == "running" and
    ([.Reservations[0].Instances[0].Tags[]? | {key:.Key,value:.Value}] as $tags
      | ($tags | any(.key == "Environment" and .value == "dev"))
      and ($tags | any(.key == "Stack" and .value == "dev-eks"))
      and ($tags | any(.key == "Phase" and .value == "eks-baseline"))
      and ($tags | any(.key == "Name" and .value == "kdt-travelplanner-dev-eks-bastion")))
  ' <<<"$details" >/dev/null || die "Bastion identity or tags do not match the retained dev-eks contract"
  log_event "bastion_identity" "retained_running_exact_tags"
}

start_keep_awake() {
  command -v caffeinate >/dev/null 2>&1 || die "macOS caffeinate is unavailable"
  caffeinate -dimsu -w "$$" >/dev/null 2>>"$LOG_FILE" &
  KEEP_AWAKE_PID=$!
  sleep 0.1
  kill -0 "$KEEP_AWAKE_PID" 2>/dev/null || die "macOS caffeinate could not be started"
  log_event "keep_awake" "started"
}

stop_keep_awake() {
  if [[ -n "$KEEP_AWAKE_PID" ]]; then
    kill "$KEEP_AWAKE_PID" 2>/dev/null || true
    wait "$KEEP_AWAKE_PID" 2>/dev/null || true
    KEEP_AWAKE_PID=""
  fi
}

reject_static_credentials() {
  local name value
  for name in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN; do
    value="${!name:-}"
    [[ -z "$value" ]] || die "static AWS credential environment variable is set: $name"
  done
}

terraform_with_auth() {
  # Terraform's AWS provider prefers AWS_PROFILE over exported short-lived
  # credentials.  Once the CLI has bootstrapped the role credentials, remove
  # only AWS_PROFILE for this child process; the profile name remains available
  # to AWS CLI configuration checks and to child operators.
  if [[ "$BOOTSTRAPPED_EPHEMERAL_CREDENTIALS" == true ]]; then
    env -u AWS_PROFILE terraform "$@"
  else
    AWS_PROFILE="$AWS_PROFILE" terraform "$@"
  fi
}

credential_expiration_epoch() {
  local value="$1"
  python3 - "$value" <<'PY'
import sys
from datetime import datetime

value = sys.argv[1]
parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
print(int(parsed.timestamp()))
PY
}

fit_lifecycle_window_to_credentials() {
  local expiration_epoch now_epoch available required reserve safety adjusted
  expiration_epoch="$(credential_expiration_epoch "$AWS_CREDENTIAL_EXPIRATION")" || die "AWS credential expiration is malformed"
  now_epoch="$(date +%s)"
  available=$((expiration_epoch - now_epoch))
  reserve="$CLEANUP_RESERVE_SECONDS"
  safety=120
  required=$((LIFECYCLE_DEADLINE_SECONDS + reserve + safety))
  if (( available < required )); then
    # Preserve a minimum five-minute cleanup reserve, but reclaim excess
    # reserve before shortening the actual deployment window.  This keeps a
    # refreshed-but-short SSO session usable without turning the horizon check
    # into a manual blocker.
    if (( reserve > 300 )); then
      reserve=300
      CLEANUP_RESERVE_SECONDS="$reserve"
    fi
    adjusted=$((available - reserve - safety))
    (( adjusted >= 300 )) || die "AWS credential horizon is too short for a safe deployment and cleanup window"
    LIFECYCLE_DEADLINE_SECONDS="$adjusted"
  fi
  (( LIFECYCLE_DEADLINE_SECONDS + CLEANUP_RESERVE_SECONDS + safety <= available )) || die "AWS credential horizon does not cover the lifecycle window"
  log_event "credential_horizon" "available=${available}s_deadline=${LIFECYCLE_DEADLINE_SECONDS}s_reserve=${CLEANUP_RESERVE_SECONDS}s"
}

bootstrap_ephemeral_credentials() {
  local profile="$AWS_PROFILE" credential_env
  reject_static_credentials
  credential_env="$(aws --profile "$profile" --region "$REGION" configure export-credentials --format env 2>>"$LOG_FILE")" || die "refreshable AWS credentials could not be exported from the configured SSO profile"
  [[ "$credential_env" == *AWS_ACCESS_KEY_ID* && "$credential_env" == *AWS_SECRET_ACCESS_KEY* && "$credential_env" == *AWS_SESSION_TOKEN* ]] || die "exported AWS credential contract is incomplete"
  # This is the AWS CLI's own shell-safe `export NAME=value` output.  Do not
  # parse it with sed or rewrite quoting; doing so corrupts session tokens.
  eval "$credential_env"
  [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" && -n "${AWS_SESSION_TOKEN:-}" ]] || die "exported AWS credentials are empty"
  AWS_CREDENTIAL_EXPIRATION="${AWS_CREDENTIAL_EXPIRATION:-}"
  [[ "$AWS_CREDENTIAL_EXPIRATION" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})$ ]] || die "exported AWS credential expiration is missing"
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_CREDENTIAL_EXPIRATION
  export AWS_CREDENTIALS_BOOTSTRAPPED=true
  BOOTSTRAPPED_EPHEMERAL_CREDENTIALS=true
  # Explicit --profile would select the expired SSO provider again.  All
  # subsequent AWS CLI calls use the exported role credentials directly.
  aws_args=(--region "$REGION")
  fit_lifecycle_window_to_credentials
  credential_heartbeat || die "bootstrapped AWS credential heartbeat failed"
  log_event "sso_refresh" "ephemeral_credentials_bootstrapped"
}

credential_heartbeat() {
  local account
  account="$(aws "${aws_args[@]}" sts get-caller-identity --query Account --output text 2>>"$LOG_FILE")" || return 1
  [[ "$account" == "$EXPECTED_ACCOUNT_ID" ]] || return 1
  log_event "credential_heartbeat" "passed"
}

verify_refreshable_sso() {
  local sso_session config_file scope
  sso_session="$(aws configure get sso_session --profile "$AWS_PROFILE" 2>>"$LOG_FILE" || true)"
  [[ "$sso_session" =~ ^[A-Za-z0-9._-]+$ ]] || die "AWS profile is not backed by a configured sso-session"
  config_file="${AWS_CONFIG_FILE:-$HOME/.aws/config}"
  [[ -f "$config_file" && ! -L "$config_file" ]] || die "AWS shared config is unavailable for SSO refresh"
  scope="$(awk -v section="[sso-session $sso_session]" '
    $0 == section { in_section=1; next }
    /^\[/ { in_section=0 }
    in_section && $1 == "sso_registration_scopes" { print substr($0, index($0, "=") + 1); exit }
  ' "$config_file" | tr -d '[:space:]')"
  [[ "$scope" == *sso:account:access* ]] || die "AWS sso-session lacks sso:account:access refresh scope"
  credential_heartbeat || die "fresh AWS credential heartbeat failed"
  log_event "sso_refresh" "configured"
}

capture_state_snapshot() {
  terraform_with_auth -chdir="$TERRAFORM_ROOT" state pull >"$STATE_FILE" 2>>"$LOG_FILE" || die "dev-eks State snapshot failed"
  chmod 0600 "$STATE_FILE"
  jq -e 'type == "object" and (.lineage | type == "string") and (.serial | type == "number") and (.resources | type == "array")' "$STATE_FILE" >/dev/null || die "dev-eks State snapshot schema is invalid"
  terraform_with_auth -chdir="$TERRAFORM_ROOT" state list \
    | awk '!/^data\./ && !/\.data\./' \
    | LC_ALL=C sort >"$ADDRESSES_FILE" 2>>"$LOG_FILE" || die "dev-eks managed-address snapshot failed"
  chmod 0600 "$ADDRESSES_FILE"
  STATE_SHA256="$(sha256sum "$STATE_FILE" | awk '{print $1}')"
  ADDRESS_SHA256="$(sha256sum "$ADDRESSES_FILE" | awk '{print $1}')"
  ADDRESS_COUNT="$(awk 'NF {n++} END {print n+0}' "$ADDRESSES_FILE")"
  STATE_LINEAGE="$(jq -er '.lineage' "$STATE_FILE")"
  STATE_SERIAL="$(jq -er '.serial | tostring' "$STATE_FILE")"
  [[ "$STATE_SHA256" =~ ^[0-9a-f]{64}$ && "$ADDRESS_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "State snapshot hashes are invalid"
}

capture_protected_state() {
  terraform_with_auth -chdir="$PERSISTENT_TERRAFORM_ROOT" state pull >"$PROTECTED_STATE_FILE" 2>>"$LOG_FILE" || die "persistent dev State snapshot failed"
  chmod 0600 "$PROTECTED_STATE_FILE"
  jq -e 'type == "object" and (.lineage | type == "string") and (.serial | type == "number")' "$PROTECTED_STATE_FILE" >/dev/null || die "persistent dev State snapshot schema is invalid"
  capture_protected_state_fingerprints "$PROTECTED_STATES_FILE"
}

capture_protected_state_fingerprints() {
  local output_path="$1" entries='[]' root key tmp raw lineage serial shape
  for root in dev dev-runtime dev-load-test; do
    key="$root/terraform.tfstate"
    tmp="$(mktemp "$REPORT_ROOT/protected-state.XXXXXX")" || die "protected State fingerprint file could not be created"
    terraform_with_auth -chdir="$SCRIPT_ROOT/infra/environments/$root" state pull >"$tmp" 2>>"$LOG_FILE" || { rm -f -- "$tmp"; die "protected State fingerprint read failed for $key"; }
    jq -e 'type == "object" and (.lineage | type == "string") and (.serial | type == "number")' "$tmp" >/dev/null || { rm -f -- "$tmp"; die "protected State fingerprint schema is invalid for $key"; }
    raw="$(sha256sum "$tmp" | awk '{print $1}')"
    lineage="$(jq -er '.lineage' "$tmp")"
    serial="$(jq -er '.serial' "$tmp")"
    shape="$(jq -cjS '[.resources[]? | {module,type,name,mode,instance_count:(.instances | length)}]' "$tmp" | sha256sum | awk '{print $1}')"
    entries="$(jq -c --arg key "$key" --arg raw "$raw" --arg lineage "$lineage" --argjson serial "$serial" --arg shape "$shape" '. + [{key:$key,raw_sha256:$raw,lineage:$lineage,serial:$serial,resource_shape_sha256:$shape}]' <<<"$entries")"
    rm -f -- "$tmp"
  done
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson entries "$entries" '{schema_version:"protected-state-fingerprint/v1",captured_at:$captured,scopes:$entries}' >"$output_path" || die "protected State fingerprint evidence write failed"
  chmod 0600 "$output_path"
}

compare_protected_state_fingerprints() {
  local before="$PROTECTED_STATES_FILE" after="$PROTECTED_STATES_AFTER_FILE"
  [[ -f "$before" && -f "$after" ]] || die "protected State fingerprint before/after evidence is missing"
  jq -e -s 'length == 2 and .[0].schema_version == "protected-state-fingerprint/v1" and .[1].schema_version == "protected-state-fingerprint/v1" and (.[0].scopes | map(.key) | sort) == ["dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"] and (.[1].scopes | map(.key) | sort) == ["dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"] and (.[0].scopes | map({key,lineage,serial,resource_shape_sha256}) | sort_by(.key)) == (.[1].scopes | map({key,lineage,serial,resource_shape_sha256}) | sort_by(.key))' "$before" "$after" >/dev/null || die "protected State semantic fingerprints changed"
  jq -n -S --arg before "$before" --arg after "$after" --slurpfile before_snapshot "$before" --slurpfile after_snapshot "$after" '{schema_version:"protected-state-comparison/v1",status:"unchanged",comparison_basis:"lineage_serial_resource_shape",raw_sha256_differences:([$before_snapshot[0].scopes[] as $b | $after_snapshot[0].scopes[] as $a | select($b.key == $a.key and $b.raw_sha256 != $a.raw_sha256) | $b.key]),before:$before,after:$after}' >"$REPORT_ROOT/protected-state-comparison.private.json"
  chmod 0600 "$REPORT_ROOT/protected-state-comparison.private.json"
}

check_normal_plan() {
  PREFLIGHT_PLAN="$REPORT_ROOT/preflight.tfplan"
  set +e
  terraform_with_auth -chdir="$TERRAFORM_ROOT" plan -input=false -detailed-exitcode -out="$PREFLIGHT_PLAN" >>"$LOG_FILE" 2>&1
  local result=$?
  set -e
  if [[ "$result" -eq 2 ]]; then
    local plan_json classification unexpected bastion_changes
    plan_json="$REPORT_ROOT/preflight-plan.private.json"
    terraform_with_auth -chdir="$TERRAFORM_ROOT" show -json "$PREFLIGHT_PLAN" >"$plan_json" 2>>"$LOG_FILE" || die "preflight plan JSON could not be read"
    chmod 0600 "$plan_json"
    unexpected="$(jq -c '[.resource_changes[]? | select(.mode == "managed" and (.change.actions // []) != ["no-op"] and ((.address | startswith("aws_s3_object.")) | not) and .address != "aws_instance.bastion")]' "$plan_json")"
    bastion_changes="$(jq -c '[.resource_changes[]? | select(.mode == "managed" and .address == "aws_instance.bastion" and (.change.actions // []) != ["no-op"])]' "$plan_json")"
    if [[ "$(jq -r 'length' <<<"$unexpected")" -eq 0 && "$(jq -r 'length' <<<"$bastion_changes")" -le 1 ]]; then
      if [[ "$(jq -r 'length' <<<"$bastion_changes")" -eq 1 ]]; then
        classification="artifact-only-with-retained-bastion-drift-not-applied"
      else
        classification="artifact-only"
      fi
      jq -n --arg status "$classification" --argjson unexpected "$unexpected" --argjson bastion "$bastion_changes" \
        '{schema_version:"dev-eks-preflight-drift/v1",status:$status,terraform_apply_performed:false,unexpected_infrastructure_changes:$unexpected,retained_bastion_changes:$bastion}' \
        >"$REPORT_ROOT/terraform-drift-classification.private.json"
      chmod 0600 "$REPORT_ROOT/terraform-drift-classification.private.json"
      PRECONDITION_MODE="deployment-resume"
      log_event "normal_plan" "$classification"
    else
      jq -n --arg status "prohibited-infrastructure-drift" --argjson unexpected "$unexpected" --argjson bastion "$bastion_changes" \
        '{schema_version:"dev-eks-preflight-drift/v1",status:$status,terraform_apply_performed:false,unexpected_infrastructure_changes:$unexpected,retained_bastion_changes:$bastion}' \
        >"$REPORT_ROOT/terraform-drift-classification.private.json"
      chmod 0600 "$REPORT_ROOT/terraform-drift-classification.private.json"
      PRECONDITION_MODE="cleanup-only"
      log_event "normal_plan" "prohibited_infrastructure_drift_cleanup_only"
    fi
  elif [[ "$result" -eq 0 ]]; then
    jq -n '{schema_version:"dev-eks-preflight-drift/v1",status:"clean",terraform_apply_performed:false,unexpected_infrastructure_changes:[],retained_bastion_changes:[]}' >"$REPORT_ROOT/terraform-drift-classification.private.json"
    chmod 0600 "$REPORT_ROOT/terraform-drift-classification.private.json"
  fi
  case "$result" in
    0) PRECONDITION_MODE="deployment-resume"; log_event "normal_plan" "clean" ;;
    2) [[ "$PRECONDITION_MODE" == "deployment-resume" ]] || PRECONDITION_MODE="cleanup-only" ;;
    *) PRECONDITION_MODE="cleanup-only"; log_event "normal_plan" "error_cleanup_only" ;;
  esac
  printf '%s\n' "$result" >"$REPORT_ROOT/normal-plan.exit"
  chmod 0600 "$REPORT_ROOT/normal-plan.exit"
}

upload_remote_helper() {
  HELPER_SHA256="$(sha256sum "$REMOTE_HELPER" | awk '{print $1}')"
  [[ "$HELPER_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "remote helper checksum is invalid"
  aws "${aws_args[@]}" s3 cp "$REMOTE_HELPER" "s3://$MONITORING_BUCKET/$HELPER_KEY" --sse AES256 >>"$LOG_FILE" 2>&1 || die "remote helper upload failed"
  SMOKE_SCRIPT_SHA256="$(sha256sum "$SMOKE_SCRIPT" | awk '{print $1}')"
  [[ "$SMOKE_SCRIPT_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "smoke verifier checksum is invalid"
  aws "${aws_args[@]}" s3 cp "$SMOKE_SCRIPT" "s3://$MONITORING_BUCKET/$SMOKE_SCRIPT_KEY" --sse AES256 >>"$LOG_FILE" 2>&1 || die "smoke verifier upload failed"
  log_event "remote_helper_upload" "verified"
}

capture_destroy_preview() {
  credential_heartbeat || die "fresh AWS credential heartbeat failed before destroy preview"
  python3 "$DESTROY_VERIFIER" \
    --mode preview \
    --terraform-root "$TERRAFORM_ROOT" \
    --aws-profile "$AWS_PROFILE" \
    --region "$REGION" \
    --expected-account-id "$EXPECTED_ACCOUNT_ID" \
    --lease "$LEASE_FILE" \
    --state-before "$STATE_FILE" \
    --addresses-before "$ADDRESSES_FILE" \
    --cluster-name "$CLUSTER_NAME" \
    --database-identifier "$DATABASE_IDENTIFIER" \
    --redis-replication-group-id "$REDIS_REPLICATION_GROUP_ID" \
    --monitoring-bucket "$MONITORING_BUCKET" \
    --parameter-name "$PARAMETER_NAME" \
    --protected-state-before "$PROTECTED_STATE_FILE" \
    --protected-states-before "$PROTECTED_STATES_FILE" \
    --protected-terraform-root "$PERSISTENT_TERRAFORM_ROOT" \
    --destroy-plan "$DESTROY_PREVIEW_PLAN" \
    --destroy-plan-json "$DESTROY_PREVIEW_PLAN_JSON" \
    --output "$REPORT_ROOT/destroy-plan-preview.private.json" \
    >>"$LOG_FILE" 2>&1 || die "exact dev-eks destroy preview failed"
  log_event "destroy_preview" "delete_only_no_apply"
}

generate_cleanup_lease() {
  local now expires account_hash
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  expires="$(date -u -v+"$((LIFECYCLE_DEADLINE_SECONDS + CLEANUP_RESERVE_SECONDS))"S +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "+$((LIFECYCLE_DEADLINE_SECONDS + CLEANUP_RESERVE_SECONDS)) seconds" +%Y-%m-%dT%H:%M:%SZ)"
  account_hash="$(printf '%s' "$EXPECTED_ACCOUNT_ID" | sha256sum | awk '{print $1}')"
  jq -n -S \
    --arg run "$RUN_ID" \
    --arg issued "$now" \
    --arg expires "$expires" \
    --arg account_hash "$account_hash" \
    --arg region "$REGION" \
    --arg backend "dev-eks/terraform.tfstate" \
    --arg lineage "$STATE_LINEAGE" \
    --arg serial "$STATE_SERIAL" \
    --arg state_sha "$STATE_SHA256" \
    --arg address_sha "$ADDRESS_SHA256" \
    --arg count "$ADDRESS_COUNT" \
    --arg cluster "$CLUSTER_NAME" \
    --arg helper_sha "$HELPER_SHA256" \
    --arg smoke_sha "$SMOKE_SCRIPT_SHA256" \
    --arg deadline "$LIFECYCLE_DEADLINE_SECONDS" \
    --arg reserve "$CLEANUP_RESERVE_SECONDS" \
    '{schema_version:"dev-eks-cleanup-lease/v1",lifecycle_run_id:$run,issued_at:$issued,expires_at:$expires,expected_account_sha256:$account_hash,expected_region:$region,terraform_backend_key:$backend,state_lineage:$lineage,state_serial:($serial|tonumber),state_sha256:$state_sha,managed_address_sha256:$address_sha,managed_address_count:($count|tonumber),cluster_name:$cluster,namespace_allowlist:["travel-planner","travel-planner-monitoring","kube-system"],ingress_name:"backend",ingress_group:"kdt-travelplanner-dev-eks",helper_sha256:$helper_sha,smoke_script_sha256:$smoke_sha,lifecycle_deadline_seconds:($deadline|tonumber),cleanup_reserve_seconds:($reserve|tonumber),permitted_actions:["delete exact Kubernetes Ingress and controller-owned ALB resources","delete exact dev-eks Kubernetes workloads and platform","apply exact dev-eks delete-only Terraform saved plan","verify native absence"],protected_backends:["dev/terraform.tfstate","dev-runtime/terraform.tfstate","dev-load-test/terraform.tfstate"],forbidden_actions:["create","update","replace","import","state edit","Cloudflare mutation","persistent resource deletion","other State deletion"]}' >"$LEASE_FILE"
  chmod 0600 "$LEASE_FILE"
  LEASE_SHA256="$(sha256sum "$LEASE_FILE" | awk '{print $1}')"
  printf '%s\n' "$LEASE_SHA256" >"$LEASE_HASH_FILE"
  chmod 0600 "$LEASE_HASH_FILE"
}

generate_authorization_receipt() {
  local now expires account_hash
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  expires="$(date -u -v+"$((LIFECYCLE_DEADLINE_SECONDS + CLEANUP_RESERVE_SECONDS))"S +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "+$((LIFECYCLE_DEADLINE_SECONDS + CLEANUP_RESERVE_SECONDS)) seconds" +%Y-%m-%dT%H:%M:%SZ)"
  account_hash="$(printf '%s' "$EXPECTED_ACCOUNT_ID" | sha256sum | awk '{print $1}')"
  jq -n -S \
    --arg run "$RUN_ID" \
    --arg now "$now" \
    --arg expires "$expires" \
    --arg plan "dev-eks-deployment-automation" \
    --arg version "$PLAN_VERSION" \
    --arg manifest_sha "$PLAN_MANIFEST_SHA256" \
    --arg handoff "$PLAN_HANDOFF_PATH" \
    --arg handoff_sha "$PLAN_HANDOFF_SHA256" \
    --arg account_hash "$account_hash" \
    --arg region "$REGION" \
    --arg backend "dev-eks/terraform.tfstate" \
    --arg lineage "$STATE_LINEAGE" \
    --arg serial "$STATE_SERIAL" \
    --arg state_sha "$STATE_SHA256" \
    --arg address_sha "$ADDRESS_SHA256" \
    --arg address_count "$ADDRESS_COUNT" \
    --arg values "$INPUT_JSON" \
    --arg values_sha "$CAPSULE_SHA256" \
    --arg resume "$RESUME_RUN_ID" \
    --arg bundle "$BUNDLE_REVISION" \
    --arg helper "$HELPER_SHA256" \
    --arg smoke "$SMOKE_SCRIPT_SHA256" \
    --arg cluster "$CLUSTER_NAME" \
    --arg image "$BACKEND_IMAGE" \
    --arg hostname "$BACKEND_HOSTNAME" \
    --arg frontend "$FRONTEND_ORIGIN" \
    '{schema_version:"dev-eks-autonomous-authorization/v1",plan_id:$plan,plan_version:($version|tonumber),manifest_sha256:$manifest_sha,handoff_path:$handoff,handoff_sha256:$handoff_sha,lifecycle_run_id:$run,issued_at:$now,expires_at:$expires,status:"active",single_use:true,expected_account_sha256:$account_hash,expected_region:$region,terraform_backend_key:$backend,state_lineage:$lineage,state_serial:($serial|tonumber),state_sha256:$state_sha,managed_address_sha256:$address_sha,managed_address_count:($address_count|tonumber),runtime_values_path:$values,runtime_values_sha256:null,prior_remote_run_id:$resume,bundle_revision_sha256:$bundle,helper_sha256:$helper,smoke_script_sha256:$smoke,cluster_name:$cluster,backend_image:$image,backend_hostname:$hostname,frontend_origin:$frontend,render_sha256:null,full_live_success:false,evidence_frozen:false,destroy_armed:false,protected_backends:["dev/terraform.tfstate","dev-runtime/terraform.tfstate","dev-load-test/terraform.tfstate"],protected_resources:["persistent VPC and subnets","ACM certificates","ECR repositories and images","profile image storage","application Secrets Manager","external DNS provider","Git and Jira lifecycle"],permitted_actions:["resume retained dev-eks Kubernetes deployment","prepare and apply exact Kubernetes stages","destroy exact dev-eks State only after frozen full success"],forbidden_actions:["Terraform create/apply","destroy before full live success","create","update","replace","import","state edit","Cloudflare mutation","persistent resource deletion","other State deletion"]}' \
    >"$AUTHORIZATION_RECEIPT"
  chmod 0600 "$AUTHORIZATION_RECEIPT"
  AUTHORIZATION_RECEIPT_SHA256="$(sha256sum "$AUTHORIZATION_RECEIPT" | awk '{print $1}')"
  printf '%s\n' "$AUTHORIZATION_RECEIPT_SHA256" >"$AUTHORIZATION_RECEIPT_SHA256_FILE"
  chmod 0600 "$AUTHORIZATION_RECEIPT_SHA256_FILE"
  log_event "authorization_receipt" "issued"
}

bind_render_authorization() {
  local render_sha="$1" updated
  [[ "$render_sha" =~ ^[0-9a-f]{64}$ ]] || die "remote prepare did not return a valid render hash"
  updated="$(mktemp "${REPORT_ROOT}/authorization-receipt.XXXXXX")" || die "could not allocate receipt update file"
  jq --arg render "$render_sha" --arg bound "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '.render_sha256=$render | .render_bound_at=$bound' "$AUTHORIZATION_RECEIPT" >"$updated" || { rm -f -- "$updated"; die "authorization receipt render binding failed"; }
  chmod 0600 "$updated"
  mv -f -- "$updated" "$AUTHORIZATION_RECEIPT"
  AUTHORIZATION_RECEIPT_SHA256="$(sha256sum "$AUTHORIZATION_RECEIPT" | awk '{print $1}')"
  printf '%s\n' "$AUTHORIZATION_RECEIPT_SHA256" >"$AUTHORIZATION_RECEIPT_SHA256_FILE"
  log_event "authorization_receipt" "render_bound"
}

confirm_cleanup_lease() {
  local response
  if [[ "$AUTONOMOUS" == true ]]; then
    LEASE_ACCEPTED=true
    log_event "cleanup_lease" "accepted_by_authorization_receipt"
    arm_deadline_watchdog
    return 0
  fi
  printf 'Scope: dev-eks State only; protected States and persistent resources are excluded.\n' >&2
  printf 'Type exactly: AUTHORIZE DEV-EKS CLEANUP %s\n' "$LEASE_SHA256" >&2
  IFS= read -r response || die "cleanup lease input was interrupted"
  [[ "$response" == "AUTHORIZE DEV-EKS CLEANUP $LEASE_SHA256" ]] || die "cleanup lease was not confirmed"
  LEASE_ACCEPTED=true
  log_event "cleanup_lease" "accepted"
  arm_deadline_watchdog
}

arm_deadline_watchdog() {
  (
    sleep "$LIFECYCLE_DEADLINE_SECONDS"
    : >"$DEADLINE_MARKER"
    printf 'phase=deadline status=expired\n' >>"$LOG_FILE"
    kill -TERM "$$" 2>/dev/null || true
  ) &
  WATCHDOG_PID=$!
  log_event "deadline_watchdog" "armed"
}

disarm_deadline_watchdog() {
  if [[ -n "$WATCHDOG_PID" ]]; then
    kill "$WATCHDOG_PID" 2>/dev/null || true
    wait "$WATCHDOG_PID" 2>/dev/null || true
    WATCHDOG_PID=""
    log_event "deadline_watchdog" "disarmed"
  fi
}

stop_active_child() {
  if [[ -n "$ACTIVE_CHILD_PID" ]]; then
    kill -TERM "$ACTIVE_CHILD_PID" 2>/dev/null || true
    wait "$ACTIVE_CHILD_PID" 2>/dev/null || true
    ACTIVE_CHILD_PID=""
  fi
}

poll_ssm() {
  local command_id="$1" stage="$2"
  local deadline invocation status poll_error="$REPORT_ROOT/${stage}-poll.stderr" failure_reason
  persist_ssm_failure() {
    local terminal_status="$1" response_code="$2"
    failure_reason="$(jq -r '.StandardErrorContent // ""' <<<"$invocation" | awk '/^stage=[A-Za-z0-9-]+ status=failed reason=[^[:cntrl:]]+$/ {line=$0} END {print line}' | tail -1)"
    if [[ -z "$failure_reason" ]]; then
      failure_reason="remote_stage_failed"
    fi
    jq -n \
      --arg schema "dev-eks-ssm-failure/v1" \
      --arg stage "$stage" \
      --arg command "$command_id" \
      --arg status "$terminal_status" \
      --arg reason "$failure_reason" \
      --argjson response_code "${response_code:-null}" \
      '{schema_version:$schema,stage:$stage,command_id:$command,status:$status,reason:$reason,response_code:$response_code}' \
      >"$REPORT_ROOT/${stage}-failure.private.json" 2>/dev/null || true
    chmod 0600 "$REPORT_ROOT/${stage}-failure.private.json" 2>/dev/null || true
  }
  deadline=$((SECONDS + SSM_TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    if ! invocation="$(aws "${aws_args[@]}" ssm get-command-invocation --command-id "$command_id" --instance-id "$BASTION_ID" --output json 2>"$poll_error")"; then
      if grep -q "InvocationDoesNotExist" "$poll_error"; then
        sleep 5
        continue
      fi
      failure_reason="ssm_invocation_poll_failed"
      jq -n --arg schema "dev-eks-ssm-failure/v1" --arg stage "$stage" --arg command "$command_id" --arg reason "$failure_reason" \
        '{schema_version:$schema,stage:$stage,command_id:$command,status:"poll_failed",reason:$reason,response_code:null}' \
        >"$REPORT_ROOT/${stage}-failure.private.json" 2>/dev/null || true
      chmod 0600 "$REPORT_ROOT/${stage}-failure.private.json" 2>/dev/null || true
      return 1
    fi
    if ! jq -e --arg command "$command_id" --arg instance "$BASTION_ID" 'type == "object" and .CommandId == $command and .InstanceId == $instance and (.Status | type == "string") and (.StandardOutputContent == null or (.StandardOutputContent | type == "string")) and (.StandardErrorContent == null or (.StandardErrorContent | type == "string"))' <<<"$invocation" >/dev/null; then
      return 1
    fi
    status="$(jq -r '.Status' <<<"$invocation")"
    case "$status" in
      Success)
        jq -e '(.ResponseCode | type == "number") and .ResponseCode == 0' <<<"$invocation" >/dev/null || return 1
        jq -r '.StandardOutputContent // ""' <<<"$invocation" >"$REPORT_ROOT/${stage}-stdout.txt"
        jq -r '.StandardErrorContent // ""' <<<"$invocation" >"$REPORT_ROOT/${stage}-stderr.txt"
        chmod 0600 "$REPORT_ROOT/${stage}-stdout.txt" "$REPORT_ROOT/${stage}-stderr.txt"
        return 0
        ;;
      Failed|Cancelled|TimedOut|Cancelling)
        persist_ssm_failure "$status" "$(jq -r '.ResponseCode // null' <<<"$invocation")"
        return 1
        ;;
      Pending|InProgress|Delayed) sleep 5 ;;
      *)
        persist_ssm_failure "$status" "$(jq -r '.ResponseCode // null' <<<"$invocation")"
        return 1
        ;;
    esac
  done
  jq -n --arg schema "dev-eks-ssm-failure/v1" --arg stage "$stage" --arg command "$command_id" \
    '{schema_version:$schema,stage:$stage,command_id:$command,status:"poll_timeout",reason:"ssm_poll_timeout",response_code:null}' \
    >"$REPORT_ROOT/${stage}-failure.private.json" 2>/dev/null || true
  chmod 0600 "$REPORT_ROOT/${stage}-failure.private.json" 2>/dev/null || true
  return 1
}

send_remote_helper_stage() {
  local stage="$1" command command_json command_id remote_work_dir remote_helper
  remote_work_dir="/var/tmp/travel-planner-dev-eks-${RESUME_RUN_ID}"
  remote_helper="$remote_work_dir/run-dev-eks-lifecycle-remote.sh"
  # shellcheck disable=SC2016
  printf -v command 'set -eu; mkdir -p %q; chmod 700 %q; aws s3 cp %q %q; test "$(sha256sum %q | awk '\''{print $1}'\'')" = %q; chmod 700 %q; export AWS_REGION=%q AWS_DEFAULT_REGION=%q; bash %q --stage %q --cluster-name %q --region %q --bucket %q --smoke-script-key %q --expected-smoke-script-sha256 %q --operator-data-key %q --expected-operator-data-sha256 %q --backend-hostname %q --monitoring-dns %q --database-identifier %q --redis-replication-group-id %q --redis-endpoint %q --redis-port %q --redis-secret-arn %q --profile-image-bucket %q --ingress-group %q --expected-helper-sha256 %q --work-dir %q' \
    "$remote_work_dir" "$remote_work_dir" "s3://$MONITORING_BUCKET/$HELPER_KEY" "$remote_helper" "$remote_helper" "$HELPER_SHA256" "$remote_helper" "$REGION" "$REGION" "$remote_helper" "$stage" "$CLUSTER_NAME" "$REGION" "$MONITORING_BUCKET" "$SMOKE_SCRIPT_KEY" "$SMOKE_SCRIPT_SHA256" "$OPERATOR_DATA_KEY" "$OPERATOR_DATA_SHA256" "$BACKEND_HOSTNAME" "$MONITORING_DNS" "$DATABASE_IDENTIFIER" "$REDIS_REPLICATION_GROUP_ID" "$REDIS_ENDPOINT" "$REDIS_PORT" "$REDIS_SECRET_ARN" "$PROFILE_IMAGE_BUCKET" "kdt-travelplanner-dev-eks" "$HELPER_SHA256" "$remote_work_dir"
  command_json="$(jq -cn --arg command "$command" '{commands:[$command]}')" || return 1
  jq -e 'type == "object" and (.commands | type == "array") and (.commands | length == 1) and (.commands[0] | type == "string" and length > 0)' <<<"$command_json" >/dev/null || return 1
  if ! command_id="$(aws "${aws_args[@]}" ssm send-command --document-name AWS-RunShellScript --instance-ids "$BASTION_ID" --parameters "$command_json" --comment "dev-eks-${RUN_ID}-${stage}" --query Command.CommandId --output text 2>>"$LOG_FILE")"; then
    if grep -Eq 'ssm:SendCommand|AccessDeniedException.*SendCommand' "$LOG_FILE" 2>/dev/null; then
      SSM_TRANSPORT_DENIED=true
    fi
    return 1
  fi
  [[ "$command_id" =~ ^[A-Za-z0-9-]{36}$ ]] || return 1
  poll_ssm "$command_id" "$stage"
}

cleanup_operator_owned_albs() {
  local load_balancers arn tags lb_json sg_ids tg_ids sg sg_tags eni_count deleted='[]' deadline
  load_balancers="$(aws "${aws_args[@]}" elbv2 describe-load-balancers --output json 2>>"$LOG_FILE")" || return 1
  while IFS= read -r arn; do
    [[ -n "$arn" ]] || continue
    tags="$(aws "${aws_args[@]}" elbv2 describe-tags --resource-arns "$arn" --output json 2>>"$LOG_FILE")" || return 1
    if ! jq -e --arg cluster "$CLUSTER_NAME" --arg stack "kdt-travelplanner-dev-eks" '
      ([.TagDescriptions[]?.Tags[]? | {key:.Key,value:.Value}] as $tags
       | ($tags | any(.key == "elbv2.k8s.aws/cluster" and .value == $cluster))
       and ($tags | any(.key == "ingress.k8s.aws/stack" and .value == $stack)))
    ' <<<"$tags" >/dev/null; then
      continue
    fi
    lb_json="$(aws "${aws_args[@]}" elbv2 describe-load-balancers --load-balancer-arns "$arn" --output json 2>>"$LOG_FILE")" || return 1
    sg_ids="$(jq -r '.LoadBalancers[0].SecurityGroups[]? // empty' <<<"$lb_json")"
    tg_ids="$(aws "${aws_args[@]}" elbv2 describe-target-groups --load-balancer-arn "$arn" --query 'TargetGroups[].TargetGroupArn' --output text 2>>"$LOG_FILE" || true)"
    aws "${aws_args[@]}" elbv2 delete-load-balancer --load-balancer-arn "$arn" >>"$LOG_FILE" 2>&1 || return 1
    deadline=$((SECONDS + 300))
    while ((SECONDS < deadline)); do
      if ! aws "${aws_args[@]}" elbv2 describe-load-balancers --load-balancer-arns "$arn" >/dev/null 2>&1; then
        break
      fi
      sleep 5
    done
    aws "${aws_args[@]}" elbv2 describe-load-balancers --load-balancer-arns "$arn" >/dev/null 2>&1 && return 1
    for tg in $tg_ids; do
      [[ "$tg" == None ]] && continue
      aws "${aws_args[@]}" elbv2 delete-target-group --target-group-arn "$tg" >>"$LOG_FILE" 2>&1 || true
    done
    for sg in $sg_ids; do
      sg_tags="$(aws "${aws_args[@]}" ec2 describe-tags --filters "Name=resource-id,Values=$sg" --output json 2>>"$LOG_FILE" || printf '{"Tags":[]}')"
      eni_count="$(aws "${aws_args[@]}" ec2 describe-network-interfaces --filters "Name=group-id,Values=$sg" --query 'length(NetworkInterfaces)' --output text 2>>"$LOG_FILE" || printf '1')"
      if jq -e --arg cluster "$CLUSTER_NAME" --arg stack "kdt-travelplanner-dev-eks" '
        ([.Tags[]? | select(.Key == "elbv2.k8s.aws/cluster" and .Value == $cluster)] | length == 1)
        and ([.Tags[]? | select(.Key == "ingress.k8s.aws/stack" and .Value == $stack)] | length == 1)
      ' <<<"$sg_tags" >/dev/null && [[ "$eni_count" == 0 ]]; then
        aws "${aws_args[@]}" ec2 delete-security-group --group-id "$sg" >>"$LOG_FILE" 2>&1 || true
      fi
    done
    deleted="$(jq -c --arg arn "$arn" '. + [$arn]' <<<"$deleted")"
  done < <(jq -r '.LoadBalancers[]?.LoadBalancerArn // empty' <<<"$load_balancers")
  verify_no_controller_owned_alb || return 1
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson deleted "$deleted" '{schema_version:"dev-eks-operator-alb-cleanup/v1",status:"success",captured_at:$captured,deleted_alb_arns:$deleted,owned_alb_count_after:0}' >"$REPORT_ROOT/operator-alb-cleanup.private.json" || return 1
  chmod 0600 "$REPORT_ROOT/operator-alb-cleanup.private.json"
}

verify_no_controller_owned_alb() {
  local load_balancers arn tags owned=0
  load_balancers="$(aws "${aws_args[@]}" elbv2 describe-load-balancers --output json 2>>"$LOG_FILE")" || return 1
  while IFS= read -r arn; do
    [[ -n "$arn" ]] || continue
    tags="$(aws "${aws_args[@]}" elbv2 describe-tags --resource-arns "$arn" --output json 2>>"$LOG_FILE")" || return 1
    if jq -e --arg cluster "$CLUSTER_NAME" --arg stack "kdt-travelplanner-dev-eks" '
      ([.TagDescriptions[]?.Tags[]? | {key:.Key,value:.Value}] as $tags
       | ($tags | any(.key == "elbv2.k8s.aws/cluster" and .value == $cluster))
       and ($tags | any(.key == "ingress.k8s.aws/stack" and .value == $stack)))
    ' <<<"$tags" >/dev/null; then
      owned=$((owned + 1))
    fi
  done < <(jq -r '.LoadBalancers[]?.LoadBalancerArn // empty' <<<"$load_balancers")
  [[ "$owned" -eq 0 ]]
}

capture_full_success_evidence() {
  local load_balancers arn tags owned='[]' count
  load_balancers="$(aws "${aws_args[@]}" elbv2 describe-load-balancers --output json 2>>"$LOG_FILE")" || return 1
  while IFS= read -r arn; do
    [[ -n "$arn" ]] || continue
    tags="$(aws "${aws_args[@]}" elbv2 describe-tags --resource-arns "$arn" --output json 2>>"$LOG_FILE")" || return 1
    if jq -e --arg cluster "$CLUSTER_NAME" --arg stack "kdt-travelplanner-dev-eks" '
      ([.TagDescriptions[]?.Tags[]? | {key:.Key,value:.Value}] as $tags
       | ($tags | any(.key == "elbv2.k8s.aws/cluster" and .value == $cluster))
       and ($tags | any(.key == "ingress.k8s.aws/stack" and .value == $stack)))
    ' <<<"$tags" >/dev/null; then
      local lb
      lb="$(jq -c --arg arn "$arn" '.LoadBalancers[] | select(.LoadBalancerArn == $arn) | {arn:.LoadBalancerArn,dns:.DNSName,state:.State.Code}' <<<"$load_balancers")"
      owned="$(jq -c --argjson item "$lb" '. + [$item]' <<<"$owned")"
    fi
  done < <(jq -r '.LoadBalancers[]?.LoadBalancerArn // empty' <<<"$load_balancers")
  count="$(jq -r 'length' <<<"$owned")"
  [[ "$count" -eq 1 ]] || return 1
  jq -e '.[0].state == "active" and (.[0].dns | type == "string" and test("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+elb\\.amazonaws\\.com$"))' <<<"$owned" >/dev/null || return 1
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg run "$RUN_ID" --arg cluster "$CLUSTER_NAME" --argjson owned "$owned" '{schema_version:"dev-eks-full-live-success/v1",status:"success",captured_at:$captured,lifecycle_run_id:$run,cluster_name:$cluster,owned_albs:$owned,backend_ready:true,monitoring_ready:true,metrics_hpa_ready:true,data_paths_ready:true,https_ready:true,destroy_armed:false,evidence_frozen:true}' >"$REPORT_ROOT/full-live-success.private.json" || return 1
  chmod 0600 "$REPORT_ROOT/full-live-success.private.json"
  FULL_SUCCESS_EVIDENCE_FROZEN=true
  DESTROY_ARMED=true
  log_event "full_live_success" "evidence_frozen_destroy_armed"
}

run_deployment_resume() {
  local result=0 render_sha="" apply_stdout="$REPORT_ROOT/deploy-kubernetes.stdout" apply_stderr="$REPORT_ROOT/deploy-kubernetes.stderr"
  log_event "deployment_resume" "started"
  if [[ "$AUTONOMOUS" == true ]]; then
    local prepare_stdout="$REPORT_ROOT/deploy-prepare.stdout" prepare_stderr="$REPORT_ROOT/deploy-prepare.stderr"
    set +e
    bash "$DEPLOY_SCRIPT" \
      --mode resume \
      --non-interactive \
      --prepare-only \
      --skip-terraform-apply \
      --aws-profile "$AWS_PROFILE" \
      --region "$REGION" \
      --expected-account-id "$EXPECTED_ACCOUNT_ID" \
      --resume-run-id "$RESUME_RUN_ID" \
      --resume-from prepare \
      --backend-image "$BACKEND_IMAGE" \
      --backend-hostname "$BACKEND_HOSTNAME" \
      --frontend-origin "$FRONTEND_ORIGIN" \
      --authorization-receipt "$AUTHORIZATION_RECEIPT" \
      >"$prepare_stdout" 2>"$prepare_stderr"
    result=$?
    if [[ "$result" -eq 0 ]]; then
      render_sha="$(grep -Eo 'render_sha256=[0-9a-f]{64}' "$prepare_stderr" | cut -d= -f2 | tail -1 || true)"
      [[ "$render_sha" =~ ^[0-9a-f]{64}$ ]] || result=1
    fi
    if [[ "$result" -eq 0 ]]; then
      bind_render_authorization "$render_sha"
      set +e
      bash "$DEPLOY_SCRIPT" \
        --mode resume \
        --non-interactive \
        --skip-terraform-apply \
        --aws-profile "$AWS_PROFILE" \
        --region "$REGION" \
        --expected-account-id "$EXPECTED_ACCOUNT_ID" \
        --resume-run-id "$RESUME_RUN_ID" \
        --resume-from namespace-secret \
        --kubernetes-render-sha256 "$render_sha" \
        --backend-image "$BACKEND_IMAGE" \
        --backend-hostname "$BACKEND_HOSTNAME" \
        --frontend-origin "$FRONTEND_ORIGIN" \
        --authorization-receipt "$AUTHORIZATION_RECEIPT" \
        >"$apply_stdout" 2>"$apply_stderr"
      result=$?
      set -e
    fi
    cat "$prepare_stdout" >>"$LOG_FILE" 2>/dev/null || true
    cat "$prepare_stderr" >>"$LOG_FILE" 2>/dev/null || true
    cat "$apply_stdout" >>"$LOG_FILE" 2>/dev/null || true
    cat "$apply_stderr" >>"$LOG_FILE" 2>/dev/null || true
  else
    set +e
    bash "$DEPLOY_SCRIPT" \
      --mode resume \
      --aws-profile "$AWS_PROFILE" \
      --region "$REGION" \
      --expected-account-id "$EXPECTED_ACCOUNT_ID" \
      --resume-run-id "$RESUME_RUN_ID" \
      --resume-from prepare \
      --backend-image "$BACKEND_IMAGE" \
      --backend-hostname "$BACKEND_HOSTNAME" \
      --frontend-origin "$FRONTEND_ORIGIN" \
      > >(tee -a "$LOG_FILE" "$apply_stdout") 2> >(tee -a "$LOG_FILE" "$apply_stderr" >&2) &
    ACTIVE_CHILD_PID=$!
    wait "$ACTIVE_CHILD_PID"
    result=$?
    ACTIVE_CHILD_PID=""
    set -e
  fi
  if [[ "$result" -eq 0 ]]; then
    INGRESS_CNAME_TARGET="$(grep -E '^C[A-Z_]+CNAME_TARGET=([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$' "$apply_stdout" | tail -1 | cut -d= -f2- || true)"
    [[ "$INGRESS_CNAME_TARGET" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]] || result=1
  fi
  if [[ "$result" -eq 0 ]]; then
    VERIFICATION_RESULT="deployment_passed"
    log_event "deployment_resume" "succeeded"
  else
    VERIFICATION_RESULT="deployment_failed"
    log_event "deployment_resume" "failed"
  fi
  return "$result"
}

operator_native_smoke() {
  local lb_json lb_count lb_arn tag_json target_groups tg target_health all_healthy deadline rds_status redis_status
  [[ "$INGRESS_CNAME_TARGET" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]] || return 1
  lb_json="$(aws "${aws_args[@]}" elbv2 describe-load-balancers --query "LoadBalancers[?DNSName=='$INGRESS_CNAME_TARGET']" --output json 2>>"$LOG_FILE")" || return 1
  lb_count="$(jq -er 'if type == "array" then length else error("ALB response is not an array") end' <<<"$lb_json")" || return 1
  [[ "$lb_count" == 1 ]] || return 1
  lb_arn="$(jq -er '.[0].LoadBalancerArn | select(type == "string" and test("^arn:aws:elasticloadbalancing:"))' <<<"$lb_json")" || return 1
  tag_json="$(aws "${aws_args[@]}" elbv2 describe-tags --resource-arns "$lb_arn" --output json 2>>"$LOG_FILE")" || return 1
  jq -e --arg cluster "$CLUSTER_NAME" --arg stack "kdt-travelplanner-dev-eks" '
    ([.TagDescriptions[]?.Tags[]? | {key:.Key,value:.Value}] as $tags
      | ($tags | any(.key == "elbv2.k8s.aws/cluster" and .value == $cluster))
      and ($tags | any(.key == "ingress.k8s.aws/stack" and .value == $stack)))
  ' <<<"$tag_json" >/dev/null || return 1
  target_groups="$(aws "${aws_args[@]}" elbv2 describe-target-groups --load-balancer-arn "$lb_arn" --query 'TargetGroups[].TargetGroupArn' --output text 2>>"$LOG_FILE")" || return 1
  [[ -n "$target_groups" && "$target_groups" != None ]] || return 1
  all_healthy=false
  deadline=$((SECONDS + 300))
  while ((SECONDS < deadline)); do
    all_healthy=true
    for tg in $target_groups; do
      target_health="$(aws "${aws_args[@]}" elbv2 describe-target-health --target-group-arn "$tg" --output json 2>>"$LOG_FILE")" || return 1
      if ! jq -e '([.TargetHealthDescriptions[]?.TargetHealth.State] | length > 0 and all(. == "healthy"))' <<<"$target_health" >/dev/null; then
        all_healthy=false
      fi
    done
    [[ "$all_healthy" == true ]] && break
    sleep 5
  done
  [[ "$all_healthy" == true ]] || return 1
  rds_status="$(aws "${aws_args[@]}" rds describe-db-instances --db-instance-identifier "$DATABASE_IDENTIFIER" --query 'DBInstances[0].DBInstanceStatus' --output text 2>>"$LOG_FILE")" || return 1
  [[ "$rds_status" == available ]] || return 1
  redis_status="$(aws "${aws_args[@]}" elasticache describe-replication-groups --replication-group-id "$REDIS_REPLICATION_GROUP_ID" --query 'ReplicationGroups[0].Status' --output text 2>>"$LOG_FILE")" || return 1
  [[ "$redis_status" == available ]] || return 1
  aws "${aws_args[@]}" s3api head-bucket --bucket "$PROFILE_IMAGE_BUCKET" >/dev/null 2>>"$LOG_FILE" || return 1
  jq -n --arg cname "$INGRESS_CNAME_TARGET" --arg alb "$lb_arn" --arg rds "$rds_status" --arg redis "$redis_status" --arg bucket "$PROFILE_IMAGE_BUCKET" \
    '{schema_version:"dev-eks-operator-cloud-smoke/v1",status:"success",cname_target:$cname,alb_arn:$alb,target_health:"healthy",rds_status:$rds,rds_available:true,redis_status:$redis,redis_available:true,profile_image_bucket:$bucket,profile_image_identity:true}' \
    >"$OPERATOR_DATA_FILE" || return 1
  chmod 0600 "$OPERATOR_DATA_FILE"
  OPERATOR_DATA_SHA256="$(sha256sum "$OPERATOR_DATA_FILE" | awk '{print $1}')"
  [[ "$OPERATOR_DATA_SHA256" =~ ^[0-9a-f]{64}$ ]] || return 1
  aws "${aws_args[@]}" s3 cp "$OPERATOR_DATA_FILE" "s3://$MONITORING_BUCKET/$OPERATOR_DATA_KEY" --sse AES256 >>"$LOG_FILE" 2>&1 || return 1
  log_event "operator_native_smoke" "alb_target_rds_redis_profile_passed"
}

probe_dependencies() {
  local db_status redis_status profile_identity
  db_status="$(aws "${aws_args[@]}" rds describe-db-instances --db-instance-identifier "$DATABASE_IDENTIFIER" --query 'DBInstances[0].DBInstanceStatus' --output text 2>>"$LOG_FILE" || true)"
  redis_status="$(aws "${aws_args[@]}" elasticache describe-replication-groups --replication-group-id "$REDIS_REPLICATION_GROUP_ID" --query 'ReplicationGroups[0].Status' --output text 2>>"$LOG_FILE" || true)"
  if [[ -n "$PROFILE_IMAGE_BUCKET" && "$PROFILE_IMAGE_BASE_URL" == https://* ]]; then
    profile_identity=true
  else
    profile_identity=false
  fi
  log_event "dependency_probe" "rds=${db_status:-unknown}_redis=${redis_status:-unknown}_profile_identity=$profile_identity"
}

run_smoke() {
  credential_heartbeat || {
    VERIFICATION_RESULT="smoke_failed"
    log_event "smoke" "credential_heartbeat_failed"
    return 1
  }
  probe_dependencies
  log_event "smoke" "started"
  if operator_native_smoke && send_remote_helper_stage smoke; then
    VERIFICATION_RESULT="smoke_passed"
    if capture_full_success_evidence; then
      log_event "smoke" "succeeded"
      return 0
    fi
    VERIFICATION_RESULT="smoke_failed"
    log_event "smoke" "success-evidence-freeze-failed"
    return 1
  fi
  VERIFICATION_RESULT="smoke_failed"
  log_event "smoke" "failed"
  return 1
}

run_cleanup_and_destroy() {
  local ingress_result=0 workload_result=0 platform_result=0 destroy_attempt=0 retry_state retry_addresses
  [[ "$FULL_SUCCESS_EVIDENCE_FROZEN" == true && "$DESTROY_ARMED" == true ]] || {
    log_event "cleanup" "blocked_until_full_success_evidence"
    return 1
  }
  CLEANUP_STARTED=true
  log_event "cleanup" "started"
  if ! credential_heartbeat; then
    REMOTE_CLEANUP_RESULT="failed"
    CLEANUP_RESULT="failed"
    log_event "cleanup" "credential_heartbeat_failed"
    return 1
  fi
  set +e
  send_remote_helper_stage cleanup-ingress
  ingress_result=$?
  if [[ "$ingress_result" -eq 0 ]]; then
    cleanup_operator_owned_albs
    ingress_result=$?
    if [[ "$ingress_result" -eq 0 ]]; then
      send_remote_helper_stage cleanup-workload
      workload_result=$?
      send_remote_helper_stage cleanup-platform
      platform_result=$?
    else
      workload_result=1
      platform_result=1
    fi
  else
    workload_result=1
    platform_result=1
  fi
  set -e
  if [[ "$ingress_result" -ne 0 && "$SSM_TRANSPORT_DENIED" == true ]]; then
    if verify_no_controller_owned_alb; then
      ingress_result=0
      workload_result=0
      platform_result=0
      REMOTE_CLEANUP_RESULT="transport_unavailable_no_alb"
      log_event "cleanup" "ssm_transport_denied_no_alb_fallback"
    fi
  fi
  if [[ "$ingress_result" -ne 0 || "$workload_result" -ne 0 || "$platform_result" -ne 0 ]]; then
    REMOTE_CLEANUP_RESULT="failed"
    CLEANUP_RESULT="failed"
    log_event "cleanup" "failed"
    return 1
  fi
  REMOTE_CLEANUP_RESULT="passed"
  log_event "cleanup" "kubernetes_resources_absent"
  # The verifier creates `terraform plan -destroy` and accepts only the
  # exact delete-only saved plan before applying it; this wrapper never calls
  # an unrestricted `terraform destroy` shortcut.
  apply_destroy_plan() {
    credential_heartbeat || return 1
    python3 "$DESTROY_VERIFIER" \
      --mode apply-destroy \
      --terraform-root "$TERRAFORM_ROOT" \
      --aws-profile "$AWS_PROFILE" \
      --region "$REGION" \
      --expected-account-id "$EXPECTED_ACCOUNT_ID" \
      --lease "$LEASE_FILE" \
      --state-before "$STATE_FILE" \
      --addresses-before "$ADDRESSES_FILE" \
      --cluster-name "$CLUSTER_NAME" \
      --database-identifier "$DATABASE_IDENTIFIER" \
      --redis-replication-group-id "$REDIS_REPLICATION_GROUP_ID" \
      --monitoring-bucket "$MONITORING_BUCKET" \
      --parameter-name "$PARAMETER_NAME" \
      --protected-state-before "$PROTECTED_STATE_FILE" \
      --protected-states-before "$PROTECTED_STATES_FILE" \
      --protected-terraform-root "$PERSISTENT_TERRAFORM_ROOT" \
      --destroy-plan "$DESTROY_PLAN" \
      --destroy-plan-json "$DESTROY_PLAN_JSON" \
      --output "$REPORT_ROOT/destroy-summary.private.json" \
      >>"$LOG_FILE" 2>&1
  }
  if ! apply_destroy_plan; then
    destroy_attempt=1
    retry_state="$REPORT_ROOT/state-retry.private.json"
    retry_addresses="$REPORT_ROOT/managed-addresses-retry.private.txt"
    terraform_with_auth -chdir="$TERRAFORM_ROOT" state pull >"$retry_state" 2>>"$LOG_FILE" || true
    terraform_with_auth -chdir="$TERRAFORM_ROOT" state list \
      | awk '!/^data\./ && !/\.data\./' \
      | LC_ALL=C sort >"$retry_addresses" 2>>"$LOG_FILE" || true
    chmod 0600 "$retry_state" "$retry_addresses"
    if [[ -s "$retry_state" && -f "$retry_addresses" ]] && cmp -s "$STATE_FILE" "$retry_state" && cmp -s "$ADDRESSES_FILE" "$retry_addresses"; then
      log_event "destroy_retry" "same_scope_reinventory"
      rm -f -- "$DESTROY_PLAN" "$DESTROY_PLAN_JSON"
      apply_destroy_plan || {
        DESTROY_RESULT="failed"
        CLEANUP_RESULT="failed"
        log_event "destroy" "failed_after_one_retry"
        return 1
      }
    else
      DESTROY_RESULT="failed"
      CLEANUP_RESULT="failed"
      log_event "destroy_retry" "blocked_scope_changed"
      log_event "destroy" "failed"
      return 1
    fi
  fi
  DESTROY_RESULT="passed"
  log_event "destroy" "applied_attempt_${destroy_attempt}"
  capture_protected_state_fingerprints "$PROTECTED_STATES_AFTER_FILE"
  compare_protected_state_fingerprints
  credential_heartbeat || {
    CLEANUP_RESULT="failed"
    log_event "retirement_verification" "credential_heartbeat_failed"
    return 1
  }
  if ! python3 "$DESTROY_VERIFIER" \
    --mode verify \
    --terraform-root "$TERRAFORM_ROOT" \
    --aws-profile "$AWS_PROFILE" \
    --region "$REGION" \
    --expected-account-id "$EXPECTED_ACCOUNT_ID" \
    --lease "$LEASE_FILE" \
    --state-before "$STATE_FILE" \
    --addresses-before "$ADDRESSES_FILE" \
    --cluster-name "$CLUSTER_NAME" \
    --database-identifier "$DATABASE_IDENTIFIER" \
    --redis-replication-group-id "$REDIS_REPLICATION_GROUP_ID" \
    --monitoring-bucket "$MONITORING_BUCKET" \
    --parameter-name "$PARAMETER_NAME" \
    --protected-state-before "$PROTECTED_STATE_FILE" \
    --protected-states-before "$PROTECTED_STATES_FILE" \
    --protected-terraform-root "$PERSISTENT_TERRAFORM_ROOT" \
    --output "$REPORT_ROOT/native-inventory.private.json" \
    >>"$LOG_FILE" 2>&1; then
    CLEANUP_RESULT="failed"
    log_event "retirement_verification" "failed"
    return 1
  fi
  CLEANUP_RESULT="passed"
  log_event "retirement_verification" "passed"
  return 0
}

finalize() {
  local original_exit="$1" cleanup_exit=0 final_status
  trap - EXIT INT TERM HUP
  [[ -f "$DEADLINE_MARKER" ]] && DEADLINE_EXPIRED=true
  disarm_deadline_watchdog
  stop_active_child
  if [[ "$LEASE_ACCEPTED" == true && "$FULL_SUCCESS_EVIDENCE_FROZEN" == true && "$DESTROY_ARMED" == true && "$CLEANUP_STARTED" == false ]]; then
    run_cleanup_and_destroy || cleanup_exit=$?
  fi
  if [[ "$LEASE_ACCEPTED" != true ]]; then
    final_status="blocked_before_lease_current_environment_still_active"
  elif [[ "$FULL_SUCCESS_EVIDENCE_FROZEN" != true ]]; then
    final_status="verification_failed_environment_retained"
  elif [[ "$cleanup_exit" -ne 0 || "$CLEANUP_RESULT" != "passed" ]]; then
    final_status="cleanup_failed_billable_residuals_present"
  elif [[ "$VERIFICATION_RESULT" == "deployment_passed" || "$VERIFICATION_RESULT" == "smoke_passed" ]]; then
    final_status="verified_and_destroyed"
  elif [[ "$VERIFICATION_RESULT" == "precondition_changed_no_deployment" ]]; then
    final_status="cleanup_only_destroyed"
  else
    final_status="verification_failed_cleanup_succeeded"
  fi
  jq -n \
    --arg status "$final_status" \
    --arg verification "$VERIFICATION_RESULT" \
    --arg cleanup "$CLEANUP_RESULT" \
    --arg remote_cleanup "$REMOTE_CLEANUP_RESULT" \
    --arg destroy "$DESTROY_RESULT" \
    --argjson deadline_expired "$DEADLINE_EXPIRED" \
    --arg run "$RUN_ID" \
    --arg evidence "$REPORT_ROOT" \
    '{schema_version:"dev-eks-ephemeral-lifecycle/v1",status:$status,verification_result:$verification,cleanup_result:$cleanup,remote_cleanup_result:$remote_cleanup,destroy_result:$destroy,deadline_expired:$deadline_expired,lifecycle_run_id:$run,evidence_root:$evidence}' >"$FINAL_SUMMARY"
  chmod 0600 "$FINAL_SUMMARY"
  if [[ "$final_status" == "verified_and_destroyed" || "$final_status" == "cleanup_only_destroyed" ]]; then
    FINAL_EXIT=0
  else
    FINAL_EXIT=1
  fi
  if [[ "$original_exit" -ne 0 && "$final_status" == "verified_and_destroyed" ]]; then
    printf 'status=verification_failed_cleanup_succeeded verification=%s cleanup=%s\n' "$VERIFICATION_RESULT" "$CLEANUP_RESULT" >&2
  else
    printf 'status=%s verification=%s cleanup=%s\n' "$final_status" "$VERIFICATION_RESULT" "$CLEANUP_RESULT" >&2
  fi
  stop_keep_awake
  exit "$FINAL_EXIT"
}

trap 'finalize "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

main() {
  log_event "preflight" "started"
  start_keep_awake
  export AWS_SDK_LOAD_CONFIG=1
  export AWS_PROFILE
  if [[ "$AUTONOMOUS" == true ]]; then
    bootstrap_ephemeral_credentials
    verify_refreshable_sso
  fi
  verify_identity_and_protected_states
  load_runtime_outputs
  verify_bastion_identity
  validate_capsule_against_outputs
  capture_state_snapshot
  capture_protected_state
  check_normal_plan
  upload_remote_helper
  generate_cleanup_lease
  capture_destroy_preview
  if [[ "$AUTONOMOUS" == true ]]; then
    generate_authorization_receipt
  fi
  confirm_cleanup_lease
  if [[ "$PRECONDITION_MODE" != "deployment-resume" ]]; then
    VERIFICATION_RESULT="precondition_changed_no_deployment"
    return 0
  fi
  credential_heartbeat || die "fresh AWS credential heartbeat failed before Kubernetes mutation"
  if ! run_deployment_resume; then
    return 1
  fi
  run_smoke || return 1
  return 0
}

main "$@"
