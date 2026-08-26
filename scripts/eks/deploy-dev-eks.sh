#!/usr/bin/env bash
set -euo pipefail

# Operator-side entrypoint. It owns approvals and SSM orchestration; all
# Kubernetes mutation happens in the private Bastion runner.
umask 077

MODE="run"
AWS_PROFILE=""
REGION="ap-northeast-2"
EXPECTED_ACCOUNT_ID=""
TERRAFORM_PLAN=""
TERRAFORM_PLAN_SHA256=""
KUBERNETES_RENDER_SHA256=""
BACKEND_IMAGE=""
BACKEND_HOSTNAME=""
FRONTEND_ORIGIN=""
RESUME_FROM=""
RESUME_RUN_ID=""
SKIP_TERRAFORM_APPLY=false
NON_INTERACTIVE=false
PREPARE_ONLY=false
AUTHORIZATION_RECEIPT=""
INPUT_CAPSULE_PATH=""
REPAIR_PREFLIGHT_PATH=""
CAPSULE_SHA256=""
CREATE_RUN_ID=""
CREATE_RECEIPT_VALIDATED=false
REPAIR_RECEIPT_VALIDATED=false
CREATE_RECEIPT_SCHEMA=""
PLAN_HANDOFF_PATH=""
PLAN_HANDOFF_EXPLICIT=false
PLAN_HANDOFF_REALPATH=""
PLAN_HANDOFF_SHA256=""
PLAN_MANIFEST_REALPATH=""
PLAN_MANIFEST_SHA256=""
PLAN_ID=""
PLAN_VERSION=""
OFFLINE_TEST=false
EXPECTED_PLAN_HANDOFF_SHA256="c2d0a19130d430a2d3d9a9e3ce14e6bd4c1a5bda0812cf128923c1464880d69d"
EXPECTED_PLAN_MANIFEST_SHA256="9171c3c0153e8a5ce50e64796b8215ba55c63401c45a394110f8b7beb378c5ab"
EXPECTED_V14_PLAN_HANDOFF_SHA256="807fdbaaac5b93b458a40dfdff5b1f25147acb873b1161c54131694ec7568865"
EXPECTED_V14_PLAN_MANIFEST_SHA256="ec39af1eb3c6e14d788f4a176ca23ce449b24cfead9e2c27af742110dff8c300"
EXPECTED_V9_PLAN_HANDOFF_SHA256="65c976f1d47c9377c534913257285a896a20d5ee2e8d0fce9fa0169f54dbfd87"
EXPECTED_V9_PLAN_MANIFEST_SHA256="0dae12f25aeb0a50ce7d5661aa2497f51c21c47f43f69f5df3b4f0d46de8c392"
EXPECTED_REPAIR_PLAN_HANDOFF_SHA256="b0441f0a4af42a807463a4d102c74e7606f36b16785f5544be365d05a626be19"
EXPECTED_REPAIR_PLAN_MANIFEST_SHA256="231da893f466968f34fadc7cd9c33eac26f72509f196da18cf93f2eac8c3d290"
EXPECTED_BACKEND_CONFIG_SHA256="86af5e85a52d52f36f4f64274d238e68985e5084f1554eab9b6364e9f2907515"
EXPECTED_CAPSULE_SHA256="3c0a636a230247a10c785822487df1ca8b5a1cfeead4d695f54afdc98d4f44f8"
EXECUTION_STARTED=false
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -z "$PLAN_HANDOFF_PATH" ]]; then
  PLAN_HANDOFF_PATH="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v15.yaml"
fi
TERRAFORM_ROOT="$SCRIPT_ROOT/infra/environments/dev-eks"
PERSISTENT_TERRAFORM_ROOT="$SCRIPT_ROOT/infra/environments/dev"
REPORT_ROOT="$SCRIPT_ROOT/evidence/eks-deploy/$RUN_ID"
REPORT_FILE="$REPORT_ROOT/deployment-summary.json"
VALUES_FILE="$REPORT_ROOT/action-values.json"
VALUES_SHA256=""
LOG_FILE="$REPORT_ROOT/orchestrator.log"
POST_PLAN=""
PLAN_SNAPSHOT_DIR=""
PLAN_SNAPSHOT=""
TARGET_KUBERNETES_VERSION=""
TRUSTED_ECR_REPOSITORY_URL=""
SSM_TIMEOUT_SECONDS="${DEV_EKS_SSM_TIMEOUT_SECONDS:-1800}"
STATE_BUCKET="kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID:-unknown}-${REGION}"
LIFECYCLE_REMOTE_HELPER="$SCRIPT_ROOT/scripts/eks/run-dev-eks-lifecycle-remote.sh"
REPAIR_SMOKE_HELPER="$SCRIPT_ROOT/scripts/eks/run-dev-eks-repair-smoke.sh"
REPAIR_BASTION_HELPER="$SCRIPT_ROOT/scripts/eks/repair-dev-eks-bastion.sh"
REPAIR_DEPLOYMENT_RUNNER="$SCRIPT_ROOT/scripts/eks/run-dev-eks-deployment.sh"
DEPLOYMENT_RUNNER_UPLOADED=false
SMOKE_VERIFIER="$SCRIPT_ROOT/monitoring/verify-eks-observability-smoke.py"
MONITORING_DNS=""
PROFILE_IMAGE_BUCKET=""
PROFILE_IMAGE_PUBLIC_BASE_URL=""
INGRESS_CNAME_TARGET=""
DEFER_CNAME_OUTPUT="${DEV_EKS_DEFER_CNAME_OUTPUT:-false}"
VPC_ID=""
PUBLIC_SUBNET_IDS=""
API_CERTIFICATE_ARN=""
NODE_GROUP_NAME=""
DATABASE_IDENTIFIER=""
REDIS_REPLICATION_GROUP_ID=""
REDIS_ENDPOINT=""
REDIS_PORT=""
REDIS_SECRET_ARN=""
MONITORING_INSTANCE_ID=""
CAPSULE_REALPATH=""
DEV_EKS_STATE_SHA256=""
DEV_EKS_STATE_LINEAGE=""
DEV_EKS_STATE_SERIAL=""
APPLY_STARTED=false
MUTATION_STARTED=false
LAST_STAGE="bootstrap"
REPAIR_STATE_TMP=""
REPAIR_STATE_TMP_DIR=""

cleanup() {
  local exit_status=$?
  if (( exit_status != 0 )) && [[ "$APPLY_STARTED" == true || "$MUTATION_STARTED" == true ]] && declare -F capture_failure_protected_state_evidence >/dev/null 2>&1; then
    if ! capture_failure_protected_state_evidence; then
      exit_status=1
      printf 'status=failed reason=protected State failure evidence could not be retained\n' >&2
    fi
  fi
  if (( exit_status != 0 )) && [[ "$APPLY_STARTED" == true || "$MUTATION_STARTED" == true ]] && declare -F capture_retained_failure_inventory >/dev/null 2>&1; then
    if ! capture_retained_failure_inventory; then
      exit_status=1
      printf 'status=failed reason=retained resource inventory could not be retained\n' >&2
    fi
  fi
  # `--help` exits before the function declarations below are evaluated.
  # Keep the EXIT trap harmless during that early path while preserving the
  # single-use receipt transition for every validated create execution.
  if [[ "$EXECUTION_STARTED" == true ]] && declare -F consume_authorization_receipt >/dev/null 2>&1; then
    if ! consume_authorization_receipt "$exit_status"; then
      exit_status=1
      printf 'status=failed reason=authorization receipt could not be terminally invalidated\n' >&2
    fi
  fi
  [[ -z "$POST_PLAN" ]] || rm -f -- "$POST_PLAN"
  [[ -z "$PLAN_SNAPSHOT_DIR" ]] || rm -rf -- "$PLAN_SNAPSHOT_DIR"
  [[ -z "$REPAIR_STATE_TMP_DIR" ]] || rm -rf -- "$REPAIR_STATE_TMP_DIR"
  trap - EXIT
  exit "$exit_status"
}
trap cleanup EXIT

usage() {
  cat >&2 <<'USAGE'
Usage: deploy-dev-eks.sh [--mode run|prepare|resume|dry-run]
  --aws-profile <profile> --region ap-northeast-2 --expected-account-id <12 digits>
  --backend-image <repository-uri>@sha256:<64 lowercase hex>
  --backend-hostname <lowercase DNS hostname>
  --frontend-origin <https origin without path/query/fragment>
  [--terraform-plan <path>] [--terraform-plan-sha256 <sha256>]
  [--kubernetes-render-sha256 <sha256>] [--resume-from prepare|namespace-secret|platform|workload|ingress-wait]
  [--resume-run-id <previous-run-id>]
  [--skip-terraform-apply] [--non-interactive] [--prepare-only]
  [--authorization-receipt <mode-0600 receipt>] [--action-values-capsule <mode-0600 capsule>]
  [--repair-preflight-json <mode-0600 v11 live preflight JSON>]
  [--plan-handoff <exact immutable authenticated handoff-v15.yaml>]
  [--offline-test]
  [--run-id <create-run-id>]

The only stable success stdout is CLOUDFLARE_CNAME_TARGET=<validated ELB hostname>.
USAGE
}

die() {
  printf 'status=failed reason=%s\n' "$1" >&2
  exit 1
}

log_event() {
  printf 'phase=%s status=%s\n' "$1" "$2" >>"$LOG_FILE"
}

while (($#)); do
  case "$1" in
    --mode) MODE="${2:?missing value for --mode}"; shift 2 ;;
    --aws-profile) AWS_PROFILE="${2:?missing value for --aws-profile}"; shift 2 ;;
    --region) REGION="${2:?missing value for --region}"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="${2:?missing value for --expected-account-id}"; shift 2 ;;
    --terraform-plan) TERRAFORM_PLAN="${2:?missing value for --terraform-plan}"; shift 2 ;;
    --terraform-plan-sha256) TERRAFORM_PLAN_SHA256="${2:?missing value for --terraform-plan-sha256}"; shift 2 ;;
    --kubernetes-render-sha256) KUBERNETES_RENDER_SHA256="${2:?missing value for --kubernetes-render-sha256}"; shift 2 ;;
    --backend-image) BACKEND_IMAGE="${2:?missing value for --backend-image}"; shift 2 ;;
    --backend-hostname) BACKEND_HOSTNAME="${2:?missing value for --backend-hostname}"; shift 2 ;;
    --frontend-origin) FRONTEND_ORIGIN="${2:?missing value for --frontend-origin}"; shift 2 ;;
    --resume-from) RESUME_FROM="${2:?missing value for --resume-from}"; shift 2 ;;
    --resume-run-id) RESUME_RUN_ID="${2:?missing value for --resume-run-id}"; shift 2 ;;
    --skip-terraform-apply) SKIP_TERRAFORM_APPLY=true; shift ;;
    --non-interactive) NON_INTERACTIVE=true; shift ;;
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --authorization-receipt) AUTHORIZATION_RECEIPT="${2:?missing value for --authorization-receipt}"; shift 2 ;;
    --action-values-capsule) INPUT_CAPSULE_PATH="${2:?missing value for --action-values-capsule}"; shift 2 ;;
    --repair-preflight-json) REPAIR_PREFLIGHT_PATH="${2:?missing value for --repair-preflight-json}"; shift 2 ;;
    --plan-handoff) PLAN_HANDOFF_PATH="${2:?missing value for --plan-handoff}"; PLAN_HANDOFF_EXPLICIT=true; shift 2 ;;
    --offline-test) OFFLINE_TEST=true; shift ;;
    --run-id) CREATE_RUN_ID="${2:?missing value for --run-id}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument" ;;
  esac
done

# Keep legacy offline/create and repair receipts reproducible when callers do
# not pass an explicit handoff.  The authenticated v15 autonomous receipt
# remains the default; selecting a legacy handoff is only possible from the
# matching receipt schema and never from an arbitrary path.
if [[ "$PLAN_HANDOFF_EXPLICIT" == false && -n "$AUTHORIZATION_RECEIPT" && -f "$AUTHORIZATION_RECEIPT" ]]; then
  case "$(jq -r '.schema_version // empty' "$AUTHORIZATION_RECEIPT" 2>/dev/null || true)" in
    dev-eks-create-authorization/v1) PLAN_HANDOFF_PATH="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v9.yaml" ;;
    dev-eks-repair-authorization/v1) PLAN_HANDOFF_PATH="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v11.yaml" ;;
  esac
fi

[[ "$MODE" =~ ^(run|prepare|resume|dry-run)$ ]] || die "mode must be run, prepare, resume or dry-run"
[[ "$REGION" == "ap-northeast-2" ]] || die "region must be ap-northeast-2 for this dev contract"
[[ "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || die "expected account id must be 12 digits"
if [[ "$OFFLINE_TEST" == true ]]; then
  [[ "$AWS_PROFILE" == "offline" ]] || die "offline-test requires the offline AWS profile"
fi
[[ "$BACKEND_IMAGE" =~ ^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || die "backend image must be an ECR URI with a lowercase sha256 digest"
[[ "$BACKEND_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "backend hostname must be a lowercase DNS hostname"
[[ "$FRONTEND_ORIGIN" =~ ^https://[a-z0-9.-]+$ ]] || die "frontend origin must be a simple https origin"

if [[ -n "$TERRAFORM_PLAN_SHA256" && ! "$TERRAFORM_PLAN_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  die "terraform plan hash must be a full lowercase sha256"
fi
if [[ -n "$KUBERNETES_RENDER_SHA256" && ! "$KUBERNETES_RENDER_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  die "kubernetes render hash must be a full lowercase sha256"
fi
[[ "$SSM_TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$SSM_TIMEOUT_SECONDS" -le 7200 ]] || die "SSM timeout must be an integer between 0 and 7200 seconds"
if [[ "$MODE" == "resume" && ! "$RESUME_FROM" =~ ^(prepare|namespace-secret|platform|workload|ingress-wait)$ ]]; then
  die "resume requires an explicit named remote stage"
fi
if [[ "$MODE" != "resume" && -n "$RESUME_FROM" ]]; then
  die "resume-from is valid only with --mode resume"
fi
if [[ "$MODE" == "resume" && -z "$RESUME_RUN_ID" ]]; then
  die "resume requires --resume-run-id for the previous remote work directory"
fi
if [[ -n "$CREATE_RUN_ID" ]]; then
  [[ "$CREATE_RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || die "run id has an invalid shape"
  RUN_ID="$CREATE_RUN_ID"
  REPORT_ROOT="$SCRIPT_ROOT/evidence/eks-deploy/$RUN_ID"
  REPORT_FILE="$REPORT_ROOT/deployment-summary.json"
  VALUES_FILE="$REPORT_ROOT/action-values.json"
  LOG_FILE="$REPORT_ROOT/orchestrator.log"
fi
if [[ "$PREPARE_ONLY" == true && ("$MODE" != "resume" || "$RESUME_FROM" != "prepare") ]]; then
  die "prepare-only is valid only with --mode resume --resume-from prepare"
fi
if [[ "$MODE" != "resume" && -n "$RESUME_RUN_ID" ]]; then
  die "resume-run-id is valid only with --mode resume"
fi
if [[ "$MODE" == "run" && "$SKIP_TERRAFORM_APPLY" == false && -z "$TERRAFORM_PLAN" ]]; then
  die "run requires --terraform-plan unless --skip-terraform-apply is explicit"
fi
if [[ "$MODE" == "run" && "$SKIP_TERRAFORM_APPLY" == false && -z "$TERRAFORM_PLAN_SHA256" ]]; then
  die "run requires --terraform-plan-sha256 for the Terraform approval"
fi
if [[ "$MODE" != "dry-run" && -z "$AUTHORIZATION_RECEIPT" ]]; then
  die "non-interactive mutation requires an authorization receipt"
fi
if [[ "$NON_INTERACTIVE" == true && "$MODE" == "run" && -z "$KUBERNETES_RENDER_SHA256" && -z "$AUTHORIZATION_RECEIPT" ]]; then
  die "non-interactive run requires --kubernetes-render-sha256"
fi
if [[ "$NON_INTERACTIVE" == true && ("$MODE" == "run" || "$MODE" == "resume") && -z "$AUTHORIZATION_RECEIPT" ]]; then
  die "non-interactive mutation requires an authorization receipt"
fi
if [[ "$NON_INTERACTIVE" == true && "$MODE" == "resume" && -z "$KUBERNETES_RENDER_SHA256" ]]; then
  [[ "$PREPARE_ONLY" == true || "$RESUME_FROM" == "prepare" ]] || die "non-interactive resume requires --kubernetes-render-sha256 unless it starts at prepare"
fi

mkdir -p "$REPORT_ROOT"
chmod 0700 "$REPORT_ROOT"

for command_name in jq sha256sum terraform mktemp; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
done
if [[ "$MODE" != "dry-run" ]]; then
  command -v aws >/dev/null 2>&1 || die "required command unavailable: aws"
fi

validate_plan_handoff() {
  [[ -f "$PLAN_HANDOFF_PATH" && ! -L "$PLAN_HANDOFF_PATH" ]] || die "exact authenticated plan handoff is missing"
  PLAN_HANDOFF_REALPATH="$(cd "$(dirname "$PLAN_HANDOFF_PATH")" && pwd)/$(basename "$PLAN_HANDOFF_PATH")"
  local canonical_handoff canonical_manifest details expected_handoff expected_manifest expected_version
  case "$PLAN_HANDOFF_REALPATH" in
    "$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v15.yaml")
      canonical_handoff="$PLAN_HANDOFF_REALPATH"
      canonical_manifest="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/plan-v15.yaml"
      expected_handoff="$EXPECTED_PLAN_HANDOFF_SHA256"
      expected_manifest="$EXPECTED_PLAN_MANIFEST_SHA256"
      expected_version=15
      ;;
    "$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v14.yaml")
      canonical_handoff="$PLAN_HANDOFF_REALPATH"
      canonical_manifest="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/plan-v14.yaml"
      expected_handoff="$EXPECTED_V14_PLAN_HANDOFF_SHA256"
      expected_manifest="$EXPECTED_V14_PLAN_MANIFEST_SHA256"
      expected_version=14
      ;;
    "$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v9.yaml")
      canonical_handoff="$PLAN_HANDOFF_REALPATH"
      canonical_manifest="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/plan-v9.yaml"
      expected_handoff="$EXPECTED_V9_PLAN_HANDOFF_SHA256"
      expected_manifest="$EXPECTED_V9_PLAN_MANIFEST_SHA256"
      expected_version=9
      ;;
    "$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v10.yaml")
      die "legacy v10 repair handoff is not accepted; use the exact v11 handoff"
      ;;
    "$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v11.yaml")
      canonical_handoff="$PLAN_HANDOFF_REALPATH"
      canonical_manifest="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/plan-v11.yaml"
      expected_handoff="$EXPECTED_REPAIR_PLAN_HANDOFF_SHA256"
      expected_manifest="$EXPECTED_REPAIR_PLAN_MANIFEST_SHA256"
      expected_version=11
      ;;
    *) die "plan handoff path is not the authenticated v15 handoff" ;;
  esac
  if [[ "$OFFLINE_TEST" == false ]]; then
    [[ "$PLAN_HANDOFF_REALPATH" == "$canonical_handoff" ]] || die "plan handoff path is not the authenticated handoff"
  else
    [[ "$PLAN_HANDOFF_REALPATH" == "$canonical_handoff" || "$PLAN_HANDOFF_REALPATH" == "$REPORT_ROOT"/* ]] || die "plan handoff path is not the authenticated v9 handoff"
  fi
  command -v ruby >/dev/null 2>&1 || die "required command unavailable: ruby for v9 handoff validation"
  PLAN_HANDOFF_SHA256="$(sha256sum "$PLAN_HANDOFF_REALPATH" | awk '{print $1}')"
  [[ "$PLAN_HANDOFF_SHA256" == "$expected_handoff" ]] || die "authenticated plan handoff hash does not match the selected contract"
  details="$(ruby -ryaml -rdigest -rjson -e '
    handoff_path = ARGV.fetch(0)
    handoff = YAML.safe_load(File.binread(handoff_path), aliases: false)
    manifest_path = handoff.fetch("manifest_path")
    manifest_bytes = File.binread(manifest_path)
    manifest = YAML.safe_load(manifest_bytes, aliases: false)
    puts JSON.generate({
      handoff_schema: handoff.fetch("schema_version"),
      manifest_schema: handoff.fetch("manifest_schema_version"),
      plan_id: handoff.fetch("plan_id"),
      version: handoff.fetch("version"),
      status: handoff.fetch("status"),
      immutable: handoff.fetch("immutable"),
      task_root: handoff.fetch("task_root"),
      manifest_path: manifest_path,
      manifest_sha256: handoff.fetch("manifest_sha256"),
      actual_manifest_sha256: Digest::SHA256.hexdigest(manifest_bytes),
      manifest_identity: {
        schema: manifest.fetch("schema_version"),
        plan_id: manifest.fetch("plan_id"),
        version: manifest.fetch("version"),
        status: manifest.fetch("status"),
        immutable: manifest.fetch("plan_artifact").fetch("immutable")
      }
    })
  ' "$PLAN_HANDOFF_REALPATH")" || die "exact v9 plan handoff could not be parsed"
  PLAN_ID="$(jq -er '.plan_id | select(type == "string")' <<<"$details")" || die "authenticated handoff plan id is missing"
  PLAN_VERSION="$(jq -er '.version | select(type == "number" and floor == .)' <<<"$details")" || die "authenticated handoff version is malformed"
  PLAN_MANIFEST_REALPATH="$(jq -er '.manifest_path | select(type == "string")' <<<"$details")" || die "authenticated handoff manifest path is missing"
  PLAN_MANIFEST_SHA256="$(jq -er '.manifest_sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' <<<"$details")" || die "authenticated handoff manifest hash is malformed"
  [[ "$PLAN_MANIFEST_SHA256" == "$expected_manifest" ]] || die "authenticated plan manifest hash does not match the selected contract"
  jq -e --arg root "$SCRIPT_ROOT" --arg handoff_schema "plan-handoff/v1" --arg manifest_schema "plan-manifest/v3" --arg manifest "$canonical_manifest" --arg actual "$PLAN_MANIFEST_SHA256" --arg offline_root "$REPORT_ROOT" --argjson expected_version "$expected_version" '
    .handoff_schema == $handoff_schema and .manifest_schema == $manifest_schema and
    .plan_id == "dev-eks-deployment-automation" and .version == $expected_version and .status == "ready" and .immutable == true and
    .task_root == $root and (.manifest_path == $manifest or ($offline_root != "" and (.manifest_path | startswith($offline_root + "/")))) and .manifest_sha256 == $actual and
    .actual_manifest_sha256 == $actual and
    .manifest_identity.schema == $manifest_schema and .manifest_identity.plan_id == "dev-eks-deployment-automation" and
    .manifest_identity.version == $expected_version and .manifest_identity.status == "ready" and .manifest_identity.immutable == true
  ' <<<"$details" >/dev/null || die "authenticated handoff or manifest identity/hash is invalid"
}

if [[ -n "$AUTHORIZATION_RECEIPT" ]]; then
  [[ "$NON_INTERACTIVE" == true ]] || die "authorization receipt requires --non-interactive"
  [[ -f "$AUTHORIZATION_RECEIPT" && ! -L "$AUTHORIZATION_RECEIPT" ]] || die "authorization receipt must be a regular file"
  [[ "$(stat -f '%Lp' "$AUTHORIZATION_RECEIPT" 2>/dev/null || stat -c '%a' "$AUTHORIZATION_RECEIPT" 2>/dev/null)" == "600" ]] || die "authorization receipt must have mode 0600"
  CREATE_RECEIPT_SCHEMA="$(jq -r '.schema_version // empty' "$AUTHORIZATION_RECEIPT" 2>/dev/null || true)"
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" || "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    [[ "$NON_INTERACTIVE" == true ]] || die "mutation receipt requires non-interactive execution"
    validate_plan_handoff
  fi
fi
if [[ -n "$INPUT_CAPSULE_PATH" ]]; then
  [[ -f "$INPUT_CAPSULE_PATH" && ! -L "$INPUT_CAPSULE_PATH" ]] || die "action-values capsule must be a regular file"
  [[ "$(stat -f '%Lp' "$INPUT_CAPSULE_PATH" 2>/dev/null || stat -c '%a' "$INPUT_CAPSULE_PATH" 2>/dev/null)" == "600" ]] || die "action-values capsule must have mode 0600"
  CAPSULE_REALPATH="$(cd "$(dirname "$INPUT_CAPSULE_PATH")" && pwd)/$(basename "$INPUT_CAPSULE_PATH")"
  jq -e '
    type == "object" and
    (.vpc_id | type == "string" and test("^vpc-[0-9a-f]+$")) and
    (.public_subnet_ids | type == "array" and length >= 2) and
    (.api_certificate_arn | type == "string" and startswith("arn:")) and
    (.backend_image | type == "string" and test("^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")) and
    (.backend_hostname | type == "string" and test("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")) and
    (.frontend_origin | type == "string" and test("^https://[a-z0-9.-]+$")) and
    (has("SecretString") | not) and (has("SecretBinary") | not)
  ' "$INPUT_CAPSULE_PATH" >/dev/null || die "action-values capsule schema or redaction check failed"
  [[ "$(jq -r '.backend_image' "$INPUT_CAPSULE_PATH")" == "$BACKEND_IMAGE" ]] || die "backend image does not match canonical action-values capsule"
  [[ "$(jq -r '.backend_hostname' "$INPUT_CAPSULE_PATH")" == "$BACKEND_HOSTNAME" ]] || die "backend hostname does not match canonical action-values capsule"
  [[ "$(jq -r '.frontend_origin' "$INPUT_CAPSULE_PATH")" == "$FRONTEND_ORIGIN" ]] || die "frontend origin does not match canonical action-values capsule"
  CAPSULE_SHA256="$(sha256sum "$INPUT_CAPSULE_PATH" | awk '{print $1}')"
  CANONICAL_CAPSULE_REALPATH="$(cd "$(dirname "$SCRIPT_ROOT/evidence/eks-deploy/20260824T133440Z-15798/action-values.json")" && pwd)/$(basename "$SCRIPT_ROOT/evidence/eks-deploy/20260824T133440Z-15798/action-values.json")"
  if [[ "$OFFLINE_TEST" == false ]]; then
    [[ "$CAPSULE_REALPATH" == "$CANONICAL_CAPSULE_REALPATH" ]] || die "production mutation requires the canonical action-values capsule path"
    [[ "$CAPSULE_SHA256" == "$EXPECTED_CAPSULE_SHA256" ]] || die "canonical action-values capsule hash does not match the authenticated plan"
  fi
fi
if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" && -z "$INPUT_CAPSULE_PATH" ]]; then
  die "v9 authorization receipt requires the action-values capsule"
fi
if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
  [[ -n "$REPAIR_PREFLIGHT_PATH" ]] || die "v11 repair requires the same read-only preflight JSON"
  [[ -f "$REPAIR_PREFLIGHT_PATH" && ! -L "$REPAIR_PREFLIGHT_PATH" ]] || die "v11 repair preflight must be a regular file"
  [[ "$(stat -f '%Lp' "$REPAIR_PREFLIGHT_PATH" 2>/dev/null || stat -c '%a' "$REPAIR_PREFLIGHT_PATH" 2>/dev/null)" == "600" ]] || die "v11 repair preflight must have mode 0600"
fi

aws_args=(--region "$REGION")
[[ -n "$AWS_PROFILE" ]] || die "aws profile is required"
if [[ "${AWS_CREDENTIALS_BOOTSTRAPPED:-false}" != true ]]; then
  aws_args+=(--profile "$AWS_PROFILE")
fi

terraform_with_auth() {
  if [[ "${AWS_CREDENTIALS_BOOTSTRAPPED:-false}" == true && -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" && -n "${AWS_SESSION_TOKEN:-}" ]]; then
    env -u AWS_PROFILE terraform "$@"
  else
    AWS_PROFILE="$AWS_PROFILE" terraform "$@"
  fi
}

REMOTE_RUN_ID="$RUN_ID"
if [[ "$MODE" == "resume" ]]; then
  [[ "$RESUME_RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || die "resume requires the previous run id"
  REMOTE_RUN_ID="$RESUME_RUN_ID"
fi

tf_output() {
  terraform_with_auth -chdir="$TERRAFORM_ROOT" output -json 2>>"$LOG_FILE" | jq -er --arg name "$1" '.[$name].value' 2>>"$LOG_FILE"
}

tf_output_string() {
  terraform_with_auth -chdir="$TERRAFORM_ROOT" output -json 2>>"$LOG_FILE" | jq -er --arg name "$1" '.[$name].value | select(type == "string")' 2>>"$LOG_FILE"
}

repair_state_expected_field() {
  local key="$1" field="$2"
  jq -er --arg key "$key" --arg field "$field" '.state_fingerprints[] | select(.key == $key) | .[$field]' "$AUTHORIZATION_RECEIPT"
}

read_repair_state_object() {
  local key="$1" output_path="$2" expected_sha expected_lineage expected_serial actual_sha actual_lineage actual_serial
  STATE_BUCKET="kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}"
  aws "${aws_args[@]}" s3api get-object --bucket "$STATE_BUCKET" --key "$key" "$output_path" >/dev/null 2>>"$LOG_FILE" || die "v11 protected State read failed for $key"
  chmod 0600 "$output_path"
  jq -e 'type == "object" and (.lineage | type == "string" and length > 0) and (.serial | type == "number" and . >= 0 and . == floor)' "$output_path" >/dev/null || die "v11 protected State schema is invalid for $key"
  expected_sha="$(repair_state_expected_field "$key" sha256)" || die "v11 State fingerprint is missing for $key"
  expected_lineage="$(repair_state_expected_field "$key" lineage)" || die "v11 State lineage is missing for $key"
  expected_serial="$(repair_state_expected_field "$key" serial)" || die "v11 State serial is missing for $key"
  actual_sha="$(sha256sum "$output_path" | awk '{print $1}')"
  actual_lineage="$(jq -er '.lineage' "$output_path")"
  actual_serial="$(jq -er '.serial' "$output_path")"
  [[ "$actual_sha" == "$expected_sha" ]] || die "v11 protected State SHA-256 differs for $key"
  [[ "$actual_lineage" == "$expected_lineage" && "$actual_serial" == "$expected_serial" ]] || die "v11 protected State identity differs for $key"
}

load_repair_state_outputs() {
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]] || return 0
  if [[ -z "$REPAIR_STATE_TMP_DIR" ]]; then
    REPAIR_STATE_TMP_DIR="$(mktemp -d "$REPORT_ROOT/repair-state.XXXXXX")" || die "v11 State temporary directory could not be created"
    chmod 0700 "$REPAIR_STATE_TMP_DIR"
  fi
  if [[ -z "$REPAIR_STATE_TMP" ]]; then
    REPAIR_STATE_TMP="$REPAIR_STATE_TMP_DIR/dev-eks.tfstate"
    read_repair_state_object "dev-eks/terraform.tfstate" "$REPAIR_STATE_TMP"
  fi
}

repair_state_output() {
  local name="$1"
  jq -er --arg name "$name" '.outputs[$name].value' "$REPAIR_STATE_TMP" || die "v11 dev-eks State output is missing: $name"
}

verify_repair_state_fingerprints() {
  local key file
  for key in dev/terraform.tfstate dev-runtime/terraform.tfstate dev-load-test/terraform.tfstate dev-eks/terraform.tfstate; do
    if [[ "$key" == "dev-eks/terraform.tfstate" && -n "$REPAIR_STATE_TMP" ]]; then
      file="$REPAIR_STATE_TMP"
    else
      load_repair_state_outputs
      file="$REPAIR_STATE_TMP_DIR/${key%/terraform.tfstate}.tfstate"
      read_repair_state_object "$key" "$file"
    fi
  done
}

verify_dev_eks_backend_contract() {
  local backend_file="$TERRAFORM_ROOT/backend.hcl" actual
  [[ -f "$backend_file" && ! -L "$backend_file" ]] || die "dev-eks backend configuration is missing"
  actual="$(sha256sum "$backend_file" | awk '{print $1}')"
  [[ "$actual" == "$EXPECTED_BACKEND_CONFIG_SHA256" ]] || die "dev-eks backend configuration hash does not match the authenticated plan"
  if [[ "$OFFLINE_TEST" == false ]]; then
    grep -Eq "^bucket[[:space:]]*=[[:space:]]*\"kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}\"[[:space:]]*$" "$backend_file" || die "dev-eks backend bucket is not exact"
  fi
  grep -Eq '^key[[:space:]]*=[[:space:]]*\"dev-eks/terraform.tfstate\"[[:space:]]*$' "$backend_file" || die "dev-eks backend key is not exact"
  grep -Eq "^region[[:space:]]*=[[:space:]]*\"${REGION}\"[[:space:]]*$" "$backend_file" || die "dev-eks backend region is not exact"
}

validate_repair_preflight() {
  local preflight_cluster
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]] || return 0
  [[ -f "$REPAIR_PREFLIGHT_PATH" && ! -L "$REPAIR_PREFLIGHT_PATH" ]] || die "v11 repair preflight is missing"
  preflight_cluster="$(jq -er '.cluster_name' "$REPAIR_PREFLIGHT_PATH")" || die "v11 repair preflight cluster is missing"
  jq -e --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg cluster "$preflight_cluster" '
    type == "object" and .schema_version == "dev-eks-v11-live-preflight/v1" and
    .expected_account_id == $account and .expected_region == $region and .cluster_name == $cluster and
    .kubernetes_version == "1.35" and .kubernetes_version_status == "STANDARD_SUPPORT" and
    (.state_fingerprints | type == "array" and length == 4) and
    (.bastion_tags | type == "object" and .Environment == "dev" and .Stack == "dev-eks" and .Phase == "eks-baseline" and .Project == "kdt-travelplanner" and .Name == "kdt-travelplanner-dev-eks-bastion")
  ' "$REPAIR_PREFLIGHT_PATH" >/dev/null || die "v11 repair preflight identity is invalid"
  jq -e --slurpfile preflight "$REPAIR_PREFLIGHT_PATH" '
    ($preflight | length == 1) and
    .bastion_instance_id == $preflight[0].bastion_instance_id and
    .cluster_name == $preflight[0].cluster_name and
    .kubernetes_version == $preflight[0].kubernetes_version and
    .kubernetes_version_status == $preflight[0].kubernetes_version_status and
    .monitoring_bucket == $preflight[0].monitoring_bucket and
    .monitoring_prefix == $preflight[0].monitoring_prefix and
    .bundle_revision_sha256 == $preflight[0].bundle_revision_sha256 and
    .retained_v9_run_id == $preflight[0].retained_v9_run_id and
    .retained_v9_plan_sha256 == $preflight[0].retained_v9_plan_sha256 and
    .state_fingerprints == $preflight[0].state_fingerprints and
    .repair_helper_sha256 == $preflight[0].helper_sha256 and
    .smoke_helper_sha256 == $preflight[0].smoke_helper_sha256
  ' "$AUTHORIZATION_RECEIPT" >/dev/null || die "v11 repair receipt does not match the supplied read-only preflight"
}

write_values() {
  local vpc_id public_subnets certificate profile_bucket profile_base
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    load_repair_state_outputs
    vpc_id="$VPC_ID"
    public_subnets="$PUBLIC_SUBNET_IDS"
    certificate="$API_CERTIFICATE_ARN"
    profile_bucket="$PROFILE_IMAGE_BUCKET"
    profile_base="$PROFILE_IMAGE_PUBLIC_BASE_URL"
  else
    vpc_id="$(tf_output vpc_id)"
    public_subnets="$(tf_output public_subnet_ids)"
    certificate="$(tf_output api_certificate_arn)"
    profile_bucket="$(tf_output profile_image_bucket_name)"
    profile_base="$(tf_output profile_image_public_base_url)"
  fi
  jq -n \
    --arg vpc_id "$vpc_id" \
    --argjson public_subnet_ids "$public_subnets" \
    --arg api_certificate_arn "$certificate" \
    --arg backend_hostname "$BACKEND_HOSTNAME" \
    --arg backend_origin "https://$BACKEND_HOSTNAME" \
    --arg backend_image "$BACKEND_IMAGE" \
    --arg frontend_origin "$FRONTEND_ORIGIN" \
    '{vpc_id:$vpc_id,public_subnet_ids:$public_subnet_ids,api_certificate_arn:$api_certificate_arn,backend_hostname:$backend_hostname,backend_origin:$backend_origin,backend_image:$backend_image,frontend_origin:$frontend_origin}' \
    >"$VALUES_FILE"
  chmod 0600 "$VALUES_FILE"
  VALUES_SHA256="$(sha256sum "$VALUES_FILE" | awk '{print $1}')"
  printf '%s\n' "$profile_bucket" "$profile_base" >/dev/null
}

validate_saved_plan() {
  [[ -f "$TERRAFORM_PLAN" && ! -L "$TERRAFORM_PLAN" ]] || die "terraform plan must be a regular file"
  local plan_real tf_real
  plan_real="$(cd "$(dirname "$TERRAFORM_PLAN")" && pwd)/$(basename "$TERRAFORM_PLAN")"
  tf_real="$(cd "$TERRAFORM_ROOT" && pwd)"
  local evidence_real="$SCRIPT_ROOT/evidence/eks-deploy"
  [[ "$plan_real" == "$tf_real/"* || "$plan_real" == "$evidence_real/"* ]] || die "terraform plan must be inside dev-eks or its private evidence root"
  TERRAFORM_PLAN="$plan_real"
  PLAN_SNAPSHOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dev-eks-plan.XXXXXX")" || die "could not allocate private Terraform plan directory"
  chmod 0700 "$PLAN_SNAPSHOT_DIR"
  PLAN_SNAPSHOT="$PLAN_SNAPSHOT_DIR/approved.tfplan"
  cp "$TERRAFORM_PLAN" "$PLAN_SNAPSHOT" || die "could not create private Terraform plan snapshot"
  chmod 0400 "$PLAN_SNAPSHOT"
  [[ -f "$PLAN_SNAPSHOT" && ! -L "$PLAN_SNAPSHOT" ]] || die "private Terraform plan snapshot is not a regular file"
  local actual
  actual="$(sha256sum "$PLAN_SNAPSHOT" | awk '{print $1}')"
  [[ "$actual" == "$TERRAFORM_PLAN_SHA256" ]] || die "terraform plan sha256 does not match the explicit approval"
  local plan_json
  plan_json="$(terraform_with_auth -chdir="$TERRAFORM_ROOT" show -json "$PLAN_SNAPSHOT")" || die "saved Terraform plan could not be decoded"
  actual="$(sha256sum "$PLAN_SNAPSHOT" | awk '{print $1}')"
  [[ "$actual" == "$TERRAFORM_PLAN_SHA256" ]] || die "private Terraform plan snapshot changed after inspection"
  jq -e '[.resource_changes[]?.change.actions[]? | select(. == "delete" or . == "replace")] | length == 0' <<<"$plan_json" >/dev/null 2>>"$LOG_FILE" || die "saved plan contains an unapproved delete/replace"
  jq -e '[.resource_changes[]?.address | select(test("(^|\\.)dev(-runtime|-load-test)?/terraform\\.tfstate|dev-runtime|dev-load-test"))] | length == 0' <<<"$plan_json" >/dev/null 2>>"$LOG_FILE" || die "saved plan contains a protected State mutation"
  jq -e '([.. | objects | select(has("endpoint_public_access")) | .endpoint_public_access] | index(true) == null)' <<<"$plan_json" >/dev/null 2>>"$LOG_FILE" || die "saved plan enables public EKS endpoint access"
  resolve_plan_target_version "$plan_json"
}

resolve_plan_target_version() {
  local plan_json="$1" variable_version planned_cluster_count planned_cluster_version
  if ! variable_version="$(jq -er '.variables.kubernetes_version.value | select(type == "string")' <<<"$plan_json" 2>>"$LOG_FILE")"; then
    die "saved Terraform plan kubernetes_version variable is missing or malformed"
  fi
  [[ "$variable_version" =~ ^1\.[0-9]{2}$ ]] || die "saved Terraform plan kubernetes_version is malformed"
  if ! planned_cluster_count="$(jq -er '[.planned_values | .. | objects | select(.type? == "aws_eks_cluster" and .mode? == "managed")] | length' <<<"$plan_json" 2>>"$LOG_FILE")"; then
    die "saved Terraform plan planned EKS cluster resources are malformed"
  fi
  [[ "$planned_cluster_count" == "1" ]] || die "saved Terraform plan must contain exactly one managed aws_eks_cluster"
  if ! planned_cluster_version="$(jq -er '[.planned_values | .. | objects | select(.type? == "aws_eks_cluster" and .mode? == "managed") | .values.version] | .[0] | select(type == "string")' <<<"$plan_json" 2>>"$LOG_FILE")"; then
    die "saved Terraform plan EKS cluster version is missing or malformed"
  fi
  [[ "$planned_cluster_version" =~ ^1\.[0-9]{2}$ ]] || die "saved Terraform plan EKS cluster version is malformed"
  [[ "$planned_cluster_version" == "$variable_version" ]] || die "saved Terraform plan kubernetes_version does not match planned EKS cluster version"
  TARGET_KUBERNETES_VERSION="$variable_version"
}

resolve_state_target_version() {
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    TARGET_KUBERNETES_VERSION="$(jq -er '.kubernetes_version' "$AUTHORIZATION_RECEIPT")" || die "v11 repair receipt cluster_version is missing or malformed"
  else
    if ! TARGET_KUBERNETES_VERSION="$(tf_output_string cluster_version)"; then
      die "dev-eks State cluster_version is missing or malformed"
    fi
  fi
  [[ "$TARGET_KUBERNETES_VERSION" =~ ^1\.[0-9]{2}$ ]] || die "dev-eks State cluster_version is malformed"
}

verify_account_and_state() {
  local account
  account="$(aws "${aws_args[@]}" sts get-caller-identity --query Account --output text)"
  [[ "$account" == "$EXPECTED_ACCOUNT_ID" ]] || die "AWS account does not match expected account"
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    validate_repair_preflight
    verify_repair_state_fingerprints
    return 0
  fi
  for state_root in dev-runtime dev-load-test; do
    local state_output
    if ! state_output="$(terraform_with_auth -chdir="$SCRIPT_ROOT/infra/environments/$state_root" state list 2>>"$LOG_FILE")"; then
      die "$state_root State precondition could not be read"
    fi
    [[ -z "$state_output" ]] || die "$state_root State is not empty; sequential ownership precondition failed"
  done
  if [[ "$MODE" == "run" && "$SKIP_TERRAFORM_APPLY" == false ]]; then
    local dev_eks_state
    if ! dev_eks_state="$(terraform_with_auth -chdir="$TERRAFORM_ROOT" state list 2>>"$LOG_FILE")"; then
      die "dev-eks State precondition could not be read"
    fi
    [[ -z "$dev_eks_state" ]] || die "dev-eks State is not empty; create-only ownership precondition failed"
  fi
}

capture_dev_eks_state_identity() {
  local output_path="${1:-$REPORT_ROOT/dev-eks-state-after.private.json}" tmp err raw_hash lineage serial
  STATE_BUCKET="kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}"
  err="$(mktemp "${REPORT_ROOT}/dev-eks-state-head.XXXXXX")" || die "dev-eks State probe file could not be created"
  tmp="$(mktemp "${REPORT_ROOT}/dev-eks-state-body.XXXXXX")" || { rm -f -- "$err"; die "dev-eks State body file could not be created"; }
  if ! aws "${aws_args[@]}" s3api get-object --bucket "$STATE_BUCKET" --key dev-eks/terraform.tfstate "$tmp" >/dev/null 2>"$err"; then
    cat "$err" >>"$LOG_FILE"
    rm -f -- "$err" "$tmp"
    die "dev-eks State identity could not be read"
  fi
  jq -e 'type == "object" and (.lineage | type == "string" and length > 0) and (.serial | type == "number" and . >= 0 and . == floor)' "$tmp" >/dev/null 2>>"$LOG_FILE" || {
    rm -f -- "$err" "$tmp"
    die "dev-eks State identity schema is invalid"
  }
  raw_hash="$(sha256sum "$tmp" | awk '{print $1}')"
  lineage="$(jq -er '.lineage' "$tmp")"
  serial="$(jq -er '.serial' "$tmp")"
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg bucket "$STATE_BUCKET" --arg key "dev-eks/terraform.tfstate" --arg raw "$raw_hash" --arg lineage "$lineage" --argjson serial "$serial" \
    '{schema_version:"dev-eks-state-identity/v1",captured_at:$captured,bucket:$bucket,key:$key,raw_sha256:$raw,lineage:$lineage,serial:$serial}' >"$output_path" || die "dev-eks State identity evidence write failed"
  chmod 0600 "$output_path"
  DEV_EKS_STATE_SHA256="$raw_hash"
  DEV_EKS_STATE_LINEAGE="$lineage"
  DEV_EKS_STATE_SERIAL="$serial"
  rm -f -- "$err" "$tmp"
}

compare_dev_eks_state_identity() {
  local before="$REPORT_ROOT/dev-eks-state-before.private.json" after="$REPORT_ROOT/dev-eks-state-after.private.json"
  [[ -f "$before" && -f "$after" && ! -L "$before" && ! -L "$after" ]] || die "dev-eks State before/after identity evidence is missing"
  jq -e -s '
    length == 2 and .[0].schema_version == "dev-eks-state-identity/v1" and .[1].schema_version == "dev-eks-state-identity/v1" and
    .[0].bucket == .[1].bucket and .[0].key == "dev-eks/terraform.tfstate" and .[1].key == "dev-eks/terraform.tfstate" and
    .[0].raw_sha256 == .[1].raw_sha256 and .[0].lineage == .[1].lineage and .[0].serial == .[1].serial
  ' "$before" "$after" >/dev/null || die "dev-eks State before/after identity differs"
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg before "$before" --arg after "$after" \
    '{schema_version:"dev-eks-state-comparison/v1",status:"unchanged",captured_at:$captured,before:$before,after:$after}' >"$REPORT_ROOT/dev-eks-state-comparison.private.json" || die "dev-eks State comparison evidence write failed"
  chmod 0600 "$REPORT_ROOT/dev-eks-state-comparison.private.json"
}

capture_protected_state_fingerprints() {
  local output_path="${1:-$REPORT_ROOT/protected-states-after.private.json}" entries='[]' key label tmp err raw_hash shape_hash
  local state_keys=(dev/terraform.tfstate dev-runtime/terraform.tfstate dev-load-test/terraform.tfstate)
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then state_keys+=(dev-eks/terraform.tfstate); fi
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" && "$SKIP_TERRAFORM_APPLY" == true && "$APPLY_STARTED" == false ]] && return 0
  STATE_BUCKET="kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}"
  for key in "${state_keys[@]}"; do
    label="${key%/terraform.tfstate}"
    err="$(mktemp "${REPORT_ROOT}/state-after-head.XXXXXX")" || die "protected State after-probe file could not be created"
    if aws "${aws_args[@]}" s3api head-object --bucket "$STATE_BUCKET" --key "$key" >/dev/null 2>"$err"; then
      tmp="$(mktemp "${REPORT_ROOT}/state-after-body.XXXXXX")" || { rm -f -- "$err"; die "protected State after-body file could not be created"; }
      aws "${aws_args[@]}" s3api get-object --bucket "$STATE_BUCKET" --key "$key" "$tmp" >/dev/null 2>>"$err" || { rm -f -- "$err" "$tmp"; die "protected State after-read failed"; }
      jq -e 'type == "object"' "$tmp" >/dev/null 2>>"$err" || { rm -f -- "$err" "$tmp"; die "protected State after-JSON is invalid"; }
      raw_hash="$(sha256sum "$tmp" | awk '{print $1}')"
      shape_hash="$(jq -cjS '[.resources[]? | {module,type,name,mode,instance_count:(.instances | length)}]' "$tmp" | sha256sum | awk '{print $1}')"
      entries="$(jq -c --arg key "$key" --arg label "$label" --arg raw "$raw_hash" --arg shape "$shape_hash" '. + [{scope:$label,key:$key,status:"present",raw_sha256:$raw,resource_shape_sha256:$shape}]' <<<"$entries")"
      rm -f -- "$tmp"
    else
      if grep -Eqi 'not found|nosuchkey|404' "$err"; then
        entries="$(jq -c --arg key "$key" --arg label "$label" '. + [{scope:$label,key:$key,status:"absent"}]' <<<"$entries")"
      else
        rm -f -- "$err"
        die "protected State after-access probe failed"
      fi
    fi
    rm -f -- "$err"
  done
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg bucket "$STATE_BUCKET" --arg region "$REGION" --argjson entries "$entries" '{schema_version:"protected-state-fingerprint/v1",captured_at:$captured,bucket:$bucket,region:$region,scopes:$entries}' >"$output_path" || die "protected State after-fingerprint write failed"
  chmod 0600 "$output_path"
}

compare_protected_state_fingerprints() {
  local before="$REPORT_ROOT/protected-states-before.private.json" after="$REPORT_ROOT/protected-states-after.private.json"
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" || "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]] || return 0
  # A delegated resume/skip-apply contract has no Terraform mutation boundary;
  # the create coordinator always captures both sides around its apply.
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" && "$SKIP_TERRAFORM_APPLY" == true && "$APPLY_STARTED" == false ]] && return 0
  [[ -f "$before" && -f "$after" && ! -L "$before" && ! -L "$after" ]] || die "protected State before/after fingerprints are missing"
  local expected_count=3
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]] && expected_count=4
  jq -e --arg bucket "$STATE_BUCKET" --arg region "$REGION" --argjson count "$expected_count" '
    .schema_version == "protected-state-fingerprint/v1" and
    .bucket == $bucket and .region == $region and (.scopes | type == "array" and length == $count)
  ' "$before" >/dev/null || die "protected State before fingerprint schema is invalid"
  jq -e --arg bucket "$STATE_BUCKET" --arg region "$REGION" --argjson count "$expected_count" '
    .schema_version == "protected-state-fingerprint/v1" and
    .bucket == $bucket and .region == $region and (.scopes | type == "array" and length == $count)
  ' "$after" >/dev/null || die "protected State after fingerprint schema is invalid"
  jq -e -s '
    .[0].scopes as $before | .[1].scopes as $after |
    ($before | sort_by(.key)) == ($after | sort_by(.key))
  ' "$before" "$after" >/dev/null || die "protected State before/after fingerprints differ"
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg before "$before" --arg after "$after" '{schema_version:"protected-state-comparison/v1",status:"unchanged",captured_at:$captured,before:$before,after:$after}' >"$REPORT_ROOT/protected-state-comparison.private.json" || die "protected State comparison evidence write failed"
  chmod 0600 "$REPORT_ROOT/protected-state-comparison.private.json"
}

capture_failure_protected_state_evidence() {
  [[ "$APPLY_STARTED" == true || "$MUTATION_STARTED" == true ]] || return 0
  local output_path="$REPORT_ROOT/protected-states-after.private.json" comparison_path="$REPORT_ROOT/protected-state-comparison.private.json" entries='[]' key label tmp err raw_hash shape_hash status
  local state_keys=(dev/terraform.tfstate dev-runtime/terraform.tfstate dev-load-test/terraform.tfstate)
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then state_keys+=(dev-eks/terraform.tfstate); fi
  for key in "${state_keys[@]}"; do
    label="${key%/terraform.tfstate}"
    err="$(mktemp "${REPORT_ROOT}/state-failure-head.XXXXXX")" || return 1
    if aws "${aws_args[@]}" s3api head-object --bucket "$STATE_BUCKET" --key "$key" >/dev/null 2>"$err"; then
      tmp="$(mktemp "${REPORT_ROOT}/state-failure-body.XXXXXX")" || { rm -f -- "$err"; return 1; }
      if aws "${aws_args[@]}" s3api get-object --bucket "$STATE_BUCKET" --key "$key" "$tmp" >/dev/null 2>>"$err" && jq -e 'type == "object"' "$tmp" >/dev/null 2>>"$err"; then
        raw_hash="$(sha256sum "$tmp" | awk '{print $1}')"
        shape_hash="$(jq -cjS '[.resources[]? | {module,type,name,mode,instance_count:(.instances | length)}]' "$tmp" | sha256sum | awk '{print $1}')"
        entries="$(jq -c --arg key "$key" --arg label "$label" --arg raw "$raw_hash" --arg shape "$shape_hash" '. + [{scope:$label,key:$key,status:"present",raw_sha256:$raw,resource_shape_sha256:$shape}]' <<<"$entries")"
      else
        entries="$(jq -c --arg key "$key" --arg label "$label" '. + [{scope:$label,key:$key,status:"unavailable"}]' <<<"$entries")"
      fi
      rm -f -- "$tmp"
    elif grep -Eqi 'not found|nosuchkey|404' "$err"; then
      entries="$(jq -c --arg key "$key" --arg label "$label" '. + [{scope:$label,key:$key,status:"absent"}]' <<<"$entries")"
    else
      entries="$(jq -c --arg key "$key" --arg label "$label" '. + [{scope:$label,key:$key,status:"unavailable"}]' <<<"$entries")"
    fi
    rm -f -- "$err"
  done
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg bucket "$STATE_BUCKET" --arg region "$REGION" --argjson entries "$entries" '{schema_version:"protected-state-fingerprint/v1",captured_at:$captured,bucket:$bucket,region:$region,scopes:$entries}' >"$output_path" || return 1
  chmod 0600 "$output_path" || return 1
  if [[ -f "$REPORT_ROOT/protected-states-before.private.json" ]]; then
    status="inconclusive"
    if jq -e -s '.[0].scopes as $before | .[1].scopes as $after | ($before | sort_by(.key)) == ($after | sort_by(.key)) and all($after[]; .status != "unavailable")' "$REPORT_ROOT/protected-states-before.private.json" "$output_path" >/dev/null 2>&1; then
      status="unchanged"
    elif jq -e -s '.[0].scopes as $before | .[1].scopes as $after | ($before | sort_by(.key)) != ($after | sort_by(.key))' "$REPORT_ROOT/protected-states-before.private.json" "$output_path" >/dev/null 2>&1; then
      status="changed"
    fi
    jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg before "$REPORT_ROOT/protected-states-before.private.json" --arg after "$output_path" --arg status "$status" '{schema_version:"protected-state-comparison/v1",status:$status,captured_at:$captured,before:$before,after:$after,terminal_failure:true}' >"$comparison_path" || return 1
    chmod 0600 "$comparison_path" || return 1
  fi
}

capture_retained_failure_inventory() {
  [[ "$APPLY_STARTED" == true || "$MUTATION_STARTED" == true ]] || return 0
  command -v aws >/dev/null 2>&1 || return 1
  local path="$REPORT_ROOT/retained-result.private.json" cluster_status="unknown" node_status="unknown" rds_status="unknown" redis_status="unknown" bastion_status="unknown" monitoring_status="unknown" nat_count="unknown" alb_count="unknown" vpc_count="unknown" subnet_count="unknown"
  if [[ -n "$CLUSTER_NAME" ]]; then cluster_status="$(aws "${aws_args[@]}" eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.status' --output text 2>>"$LOG_FILE" || printf 'unknown')"; fi
  if [[ -n "$NODE_GROUP_NAME" && -n "$CLUSTER_NAME" ]]; then node_status="$(aws "${aws_args[@]}" eks describe-nodegroup --cluster-name "$CLUSTER_NAME" --nodegroup-name "$NODE_GROUP_NAME" --query 'nodegroup.status' --output text 2>>"$LOG_FILE" || printf 'unknown')"; fi
  if [[ -n "$DATABASE_IDENTIFIER" ]]; then rds_status="$(aws "${aws_args[@]}" rds describe-db-instances --db-instance-identifier "$DATABASE_IDENTIFIER" --query 'DBInstances[0].DBInstanceStatus' --output text 2>>"$LOG_FILE" || printf 'unknown')"; fi
  if [[ -n "$REDIS_REPLICATION_GROUP_ID" ]]; then redis_status="$(aws "${aws_args[@]}" elasticache describe-replication-groups --replication-group-id "$REDIS_REPLICATION_GROUP_ID" --query 'ReplicationGroups[0].Status' --output text 2>>"$LOG_FILE" || printf 'unknown')"; fi
  if [[ -n "$BASTION_ID" ]]; then bastion_status="$(aws "${aws_args[@]}" ec2 describe-instances --instance-ids "$BASTION_ID" --query 'Reservations[0].Instances[0].State.Name' --output text 2>>"$LOG_FILE" || printf 'unknown')"; fi
  if [[ -n "$MONITORING_INSTANCE_ID" ]]; then monitoring_status="$(aws "${aws_args[@]}" ec2 describe-instances --instance-ids "$MONITORING_INSTANCE_ID" --query 'Reservations[0].Instances[0].State.Name' --output text 2>>"$LOG_FILE" || printf 'unknown')"; fi
  nat_count="$(aws "${aws_args[@]}" ec2 describe-nat-gateways --filter Name=tag:Environment,Values=dev Name=tag:Stack,Values=dev-eks --query 'length(NatGateways)' --output text 2>>"$LOG_FILE" || printf 'unknown')"
  if [[ "$INGRESS_CNAME_TARGET" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]]; then
    alb_count="$(aws "${aws_args[@]}" elbv2 describe-load-balancers --query "length(LoadBalancers[?DNSName=='$INGRESS_CNAME_TARGET'])" --output text 2>>"$LOG_FILE" || printf 'unknown')"
  else
    alb_count="unknown"
  fi
  # VPC/subnets are persistent dev-owned inputs, not disposable lifecycle resources.
  # Do not report a tag-filter count as if they were removed.
  vpc_count="protected_input"
  subnet_count="protected_input"
  jq -n --arg stage "$LAST_STAGE" --arg cluster "$CLUSTER_NAME" --arg node "$NODE_GROUP_NAME" --arg rds_id "$DATABASE_IDENTIFIER" --arg redis_id "$REDIS_REPLICATION_GROUP_ID" --arg bastion "$BASTION_ID" --arg monitoring "$MONITORING_INSTANCE_ID" --arg cluster_status "$cluster_status" --arg node_status "$node_status" --arg rds_status "$rds_status" --arg redis_status "$redis_status" --arg bastion_status "$bastion_status" --arg monitoring_status "$monitoring_status" --arg nat_count "$nat_count" --arg alb_count "$alb_count" --arg vpc_count "$vpc_count" --arg subnet_count "$subnet_count" '{schema_version:"dev-eks-retained-result/v1",status:"failed",environment_retained:true,failed_stage:$stage,resources:{cluster:{name:$cluster,status:$cluster_status},node_group:{name:$node,status:$node_status},rds:{identifier:$rds_id,status:$rds_status},redis:{replication_group_id:$redis_id,status:$redis_status},bastion:{instance_id:$bastion,status:$bastion_status},monitoring:{instance_id:$monitoring,status:$monitoring_status},nat_gateways:{count:$nat_count},load_balancers:{count:$alb_count},vpc:{count:$vpc_count},subnets:{count:$subnet_count}}}' >"$path" || return 1
  chmod 0600 "$path" || return 1
}

verify_infrastructure_readiness() {
  local cluster_status node_status rds_status redis_status bastion_json monitoring_json readiness_path
  readiness_path="$REPORT_ROOT/infrastructure-readiness.private.json"
  cluster_status="$(aws "${aws_args[@]}" eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.status' --output text 2>>"$LOG_FILE")" || die "EKS cluster readiness lookup failed"
  [[ "$cluster_status" == "ACTIVE" ]] || die "EKS cluster is not ACTIVE"
  node_status="$(aws "${aws_args[@]}" eks describe-nodegroup --cluster-name "$CLUSTER_NAME" --nodegroup-name "$NODE_GROUP_NAME" --query 'nodegroup.status' --output text 2>>"$LOG_FILE")" || die "EKS node group readiness lookup failed"
  [[ "$node_status" == "ACTIVE" ]] || die "EKS node group is not ACTIVE"
  rds_status="$(aws "${aws_args[@]}" rds describe-db-instances --db-instance-identifier "$DATABASE_IDENTIFIER" --query 'DBInstances[0].DBInstanceStatus' --output text 2>>"$LOG_FILE")" || die "RDS readiness lookup failed"
  [[ "$rds_status" == "available" ]] || die "RDS instance is not available"
  redis_status="$(aws "${aws_args[@]}" elasticache describe-replication-groups --replication-group-id "$REDIS_REPLICATION_GROUP_ID" --query 'ReplicationGroups[0].Status' --output text 2>>"$LOG_FILE")" || die "Redis readiness lookup failed"
  [[ "$redis_status" == "available" ]] || die "Redis replication group is not available"
  bastion_json="$(aws "${aws_args[@]}" ec2 describe-instances --instance-ids "$BASTION_ID" --output json 2>>"$LOG_FILE")" || die "Bastion readiness lookup failed"
  jq -e --arg id "$BASTION_ID" '
    ([.Reservations[]?.Instances[]? | select(.InstanceId == $id)] | length == 1)
    and ([.Reservations[]?.Instances[]? | select(.InstanceId == $id) | .State.Name] | .[0] == "running")
    and ([.Reservations[]?.Instances[]? | select(.InstanceId == $id) | .Tags[]? | select(.Key == "Environment" and .Value == "dev")] | length == 1)
    and ([.Reservations[]?.Instances[]? | select(.InstanceId == $id) | .Tags[]? | select(.Key == "Stack" and .Value == "dev-eks")] | length == 1)
    and ([.Reservations[]?.Instances[]? | select(.InstanceId == $id) | .Tags[]? | select(.Key == "Name" and .Value == "kdt-travelplanner-dev-eks-bastion")] | length == 1)
  ' <<<"$bastion_json" >/dev/null || die "Bastion is not the exact running tagged private target"
  monitoring_json="$(aws "${aws_args[@]}" ec2 describe-instances --instance-ids "$MONITORING_INSTANCE_ID" --output json 2>>"$LOG_FILE")" || die "Monitoring readiness lookup failed"
  jq -e --arg id "$MONITORING_INSTANCE_ID" '([.Reservations[]?.Instances[]? | select(.InstanceId == $id) | .State.Name] | .[0] == "running")' <<<"$monitoring_json" >/dev/null || die "Monitoring instance is not running"
  jq -n --arg cluster "$cluster_status" --arg node "$node_status" --arg rds "$rds_status" --arg redis "$redis_status" --arg bastion "$BASTION_ID" --arg monitoring "$MONITORING_INSTANCE_ID" '{schema_version:"infrastructure-readiness/v1",cluster_status:$cluster,node_group_status:$node,rds_status:$rds,redis_status:$redis,bastion_instance_id:$bastion,monitoring_instance_id:$monitoring}' >"$readiness_path" || die "infrastructure readiness evidence write failed"
  chmod 0600 "$readiness_path"
}

verify_eks_support_status() {
  local response result_count actual_version cluster_type version_status
  if ! response="$(aws "${aws_args[@]}" eks describe-cluster-versions \
    --cluster-type eks \
    --cluster-versions "$TARGET_KUBERNETES_VERSION" \
    --no-paginate \
    --output json 2>>"$LOG_FILE")"; then
    die "EKS support metadata lookup failed"
  fi
  jq -e 'type == "object" and (.clusterVersions | type == "array")' <<<"$response" >/dev/null 2>>"$LOG_FILE" || die "EKS support metadata response schema is invalid"
  if ! result_count="$(jq -er '.clusterVersions | length' <<<"$response" 2>>"$LOG_FILE")"; then
    die "EKS support metadata response schema is invalid"
  fi
  [[ "$result_count" == "1" ]] || die "EKS support metadata result cardinality is invalid"
  jq -e '.clusterVersions[0] | type == "object"' <<<"$response" >/dev/null 2>>"$LOG_FILE" || die "EKS support metadata item schema is invalid"
  if ! actual_version="$(jq -er '.clusterVersions[0].clusterVersion | select(type == "string")' <<<"$response" 2>>"$LOG_FILE")"; then
    die "EKS support metadata clusterVersion is missing or malformed"
  fi
  [[ "$actual_version" == "$TARGET_KUBERNETES_VERSION" ]] || die "EKS support metadata version does not match target"
  if ! cluster_type="$(jq -er '.clusterVersions[0].clusterType | select(type == "string")' <<<"$response" 2>>"$LOG_FILE")"; then
    die "EKS support metadata clusterType is missing or malformed"
  fi
  [[ "$cluster_type" == "eks" ]] || die "EKS support metadata clusterType is not eks"
  if ! version_status="$(jq -er '.clusterVersions[0].versionStatus | select(type == "string")' <<<"$response" 2>>"$LOG_FILE")"; then
    die "EKS support metadata versionStatus is missing or malformed"
  fi
  case "$version_status" in
    STANDARD_SUPPORT|EXTENDED_SUPPORT) ;;
    UNSUPPORTED) die "EKS target $TARGET_KUBERNETES_VERSION is UNSUPPORTED" ;;
    *) die "EKS support metadata versionStatus is unknown" ;;
  esac
}

validate_ecr_repository_url() {
  local repository_url="$1" account region repository
  if [[ "$repository_url" =~ ^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/([a-z0-9][a-z0-9._/-]*[a-z0-9])$ ]]; then
    account="${BASH_REMATCH[1]}"
    region="${BASH_REMATCH[2]}"
    repository="${BASH_REMATCH[3]}"
  else
    die "trusted Backend ECR repository URL is invalid"
  fi
  [[ "$account" == "$EXPECTED_ACCOUNT_ID" ]] || die "trusted Backend ECR repository account does not match expected account"
  [[ "$region" == "$REGION" ]] || die "trusted Backend ECR repository region does not match expected region"
  [[ "$repository" != *".."* && "$repository" != *"//"* ]] || die "trusted Backend ECR repository path is invalid"
  printf '%s' "$repository_url"
}

validate_backend_image_provenance() {
  local trusted_repository_url image_repository image_digest actual_digest repository_name persistent_outputs
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    local persistent_state_tmp
    load_repair_state_outputs
    persistent_state_tmp="$REPAIR_STATE_TMP_DIR/persistent.tfstate"
    read_repair_state_object "dev/terraform.tfstate" "$persistent_state_tmp"
    trusted_repository_url="$(jq -er '.outputs.backend_ecr_repository_url.value | select(type == "string")' "$persistent_state_tmp")" || die "v11 persistent State has no backend_ecr_repository_url output"
    rm -f -- "$persistent_state_tmp"
  else
    persistent_outputs="$(terraform_with_auth -chdir="$PERSISTENT_TERRAFORM_ROOT" output -json 2>>"$LOG_FILE")" || die "persistent dev State ECR output could not be read"
    trusted_repository_url="$(jq -er '.backend_ecr_repository_url.value' <<<"$persistent_outputs")" || die "persistent dev State has no backend_ecr_repository_url output"
  fi
  TRUSTED_ECR_REPOSITORY_URL="$(validate_ecr_repository_url "$trusted_repository_url")"
  [[ "$BACKEND_IMAGE" =~ ^(.+)@sha256:([0-9a-f]{64})$ ]] || die "backend image must use a lowercase sha256 digest"
  image_repository="${BASH_REMATCH[1]}"
  image_digest="${BASH_REMATCH[2]}"
  [[ "$image_repository" == "$TRUSTED_ECR_REPOSITORY_URL" ]] || die "backend image repository must exactly match trusted persistent-dev ECR repository"
  repository_name="${TRUSTED_ECR_REPOSITORY_URL#*/}"
  actual_digest="$(aws "${aws_args[@]}" ecr describe-images \
    --repository-name "$repository_name" \
    --registry-id "$EXPECTED_ACCOUNT_ID" \
    --image-ids "imageDigest=sha256:$image_digest" \
    --query 'imageDetails[0].imageDigest' \
    --output text)" || die "Backend image digest could not be verified in ECR"
  [[ "$actual_digest" == "sha256:$image_digest" ]] || die "Backend image digest is not present in the trusted ECR repository"
}

verify_live_preflight() {
  verify_dev_eks_backend_contract
  verify_account_and_state
  if [[ "$MODE" != "run" || "$SKIP_TERRAFORM_APPLY" == true ]]; then
    resolve_state_target_version
  fi
  verify_eks_support_status
  validate_backend_image_provenance
}

parse_receipt_epoch() {
  local value="$1"
  date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$value" +%s 2>/dev/null || date -u -d "$value" +%s 2>/dev/null
}

consume_create_receipt() {
  local exit_status="${1:-0}" terminal_result="failed"
  if [[ "$exit_status" -eq 0 && "$CREATE_RECEIPT_VALIDATED" == true ]]; then terminal_result="completed"; fi
  [[ -n "$AUTHORIZATION_RECEIPT" && -f "$AUTHORIZATION_RECEIPT" && ! -L "$AUTHORIZATION_RECEIPT" ]] || return 0
  jq -e '.schema_version == "dev-eks-create-authorization/v1" and .status == "active"' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1 || return 0
  local consumed
  consumed="$(mktemp "${AUTHORIZATION_RECEIPT}.consumed.XXXXXX")" || return 1
  jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg result "$terminal_result" '.status="consumed" | .consumed_at=$now | .terminal_result=$result' "$AUTHORIZATION_RECEIPT" >"$consumed" || { rm -f -- "$consumed"; return 1; }
  chmod 0600 "$consumed" || { rm -f -- "$consumed"; return 1; }
  mv -f -- "$consumed" "$AUTHORIZATION_RECEIPT" || { rm -f -- "$consumed"; return 1; }
  CREATE_RECEIPT_VALIDATED=false
}

consume_repair_receipt() {
  local exit_status="${1:-0}" terminal_result="failed"
  if [[ "$exit_status" -eq 0 && "$REPAIR_RECEIPT_VALIDATED" == true ]]; then terminal_result="completed"; fi
  [[ -n "$AUTHORIZATION_RECEIPT" && -f "$AUTHORIZATION_RECEIPT" && ! -L "$AUTHORIZATION_RECEIPT" ]] || return 0
  jq -e '.schema_version == "dev-eks-repair-authorization/v1" and .status == "active"' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1 || return 0
  if [[ "$exit_status" -ne 0 ]] && jq -e '.completion_lease == true and .continuity_verified == true' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1; then
    return 0
  fi
  local consumed
  consumed="$(mktemp "${AUTHORIZATION_RECEIPT}.consumed.XXXXXX")" || return 1
  jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg result "$terminal_result" '.status="consumed" | .consumed_at=$now | .terminal_result=$result' "$AUTHORIZATION_RECEIPT" >"$consumed" || { rm -f -- "$consumed"; return 1; }
  chmod 0600 "$consumed" || { rm -f -- "$consumed"; return 1; }
  mv -f -- "$consumed" "$AUTHORIZATION_RECEIPT" || { rm -f -- "$consumed"; return 1; }
  REPAIR_RECEIPT_VALIDATED=false
}

consume_authorization_receipt() {
  case "$CREATE_RECEIPT_SCHEMA" in
    dev-eks-create-authorization/v1) consume_create_receipt "$@" ;;
    dev-eks-repair-authorization/v1) consume_repair_receipt "$@" ;;
    *) return 0 ;;
  esac
}

validate_create_receipt() {
  local phase="${1:-pre-apply}" expires expires_epoch expected_plan expected_action target_version
  validate_plan_handoff
  [[ -n "$AUTHORIZATION_RECEIPT" ]] || die "v9 create authorization receipt is required"
  [[ -f "$AUTHORIZATION_RECEIPT" && ! -L "$AUTHORIZATION_RECEIPT" ]] || die "v9 create authorization receipt must be a regular file"
  CREATE_RECEIPT_SCHEMA="$(jq -r '.schema_version // empty' "$AUTHORIZATION_RECEIPT" 2>/dev/null || true)"
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" ]] || die "authorization receipt schema is not v9 create-only"
  [[ "$TERRAFORM_PLAN_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "v9 create authorization requires a non-empty Terraform plan hash"
  expected_plan="$TERRAFORM_PLAN_SHA256"
  expected_action="APPLY DEV-EKS CREATE-AND-RETAIN $expected_plan"
  target_version="$TARGET_KUBERNETES_VERSION"
  local backend_config_sha256
  [[ -f "$TERRAFORM_ROOT/backend.hcl" && ! -L "$TERRAFORM_ROOT/backend.hcl" ]] || die "dev-eks backend configuration is missing"
  backend_config_sha256="$(sha256sum "$TERRAFORM_ROOT/backend.hcl" | awk '{print $1}')"
  jq -e --arg run "$RUN_ID" --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg plan "$expected_plan" --arg backend "dev-eks/terraform.tfstate" --arg backend_config "$backend_config_sha256" --arg capsule "$CAPSULE_SHA256" --arg capsule_path "$CAPSULE_REALPATH" --arg image "$BACKEND_IMAGE" --arg hostname "$BACKEND_HOSTNAME" --arg frontend "$FRONTEND_ORIGIN" --arg action "$expected_action" --arg target_version "$target_version" --arg plan_id "$PLAN_ID" --argjson plan_version "$PLAN_VERSION" --arg manifest_sha "$PLAN_MANIFEST_SHA256" --arg manifest_path "$PLAN_MANIFEST_REALPATH" --arg handoff_path "$PLAN_HANDOFF_REALPATH" --arg handoff_sha "$PLAN_HANDOFF_SHA256" '
    type == "object" and
    .schema_version == "dev-eks-create-authorization/v1" and
    .handoff_schema_version == "plan-handoff/v1" and .manifest_schema_version == "plan-manifest/v3" and
    .plan_id == $plan_id and .plan_version == $plan_version and
    .manifest_sha256 == $manifest_sha and .manifest_path == $manifest_path and
    .handoff_path == $handoff_path and .handoff_sha256 == $handoff_sha and
    .run_id == $run and .status == "active" and .single_use == true and
    .expected_account_id == $account and .expected_region == $region and
    .terraform_backend_key == $backend and .terraform_backend_config_sha256 == $backend_config and .terraform_plan_sha256 == $plan and
    .input_capsule_path == $capsule_path and .input_capsule_sha256 == $capsule and .backend_image == $image and
    .backend_hostname == $hostname and .frontend_origin == $frontend and
    .kubernetes_version_status == "STANDARD_SUPPORT" and ($target_version == "" or .kubernetes_version == $target_version) and
    (.protected_backends | type == "array" and sort == ["dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"]) and
    (.protected_resources | type == "array" and length >= 4 and index("persistent VPC and subnets") != null and index("ACM certificates") != null and index("ECR repositories and images") != null and index("external DNS provider") != null) and
    (.permitted_actions | type == "array" and index("apply exact create/update-only dev-eks Terraform plan") != null and index("run exact staged Kubernetes deployment through tagged private Bastion") != null and index("retain created dev-eks resources") != null and all(.[]; (tostring | test("destroy|delete|Cloudflare|protected State"; "i") | not))) and
    (.forbidden_actions | type == "array" and index("terraform destroy") != null and index("Kubernetes delete") != null and index("Cloudflare mutation") != null and index("protected State mutation") != null) and
    (.paid_approval.status == "approved" and .paid_approval.action == $action and .paid_approval.plan_sha256 == $plan)' "$AUTHORIZATION_RECEIPT" >/dev/null || die "v9 authorization receipt binding or approval is invalid"
  expires="$(jq -er '.expires_at | select(type == "string")' "$AUTHORIZATION_RECEIPT")" || die "v9 authorization receipt expiry is missing"
  expires_epoch="$(parse_receipt_epoch "$expires")" || die "v9 authorization receipt expiry is malformed"
  (( expires_epoch > $(date +%s) )) || die "v9 authorization receipt is expired"
  if [[ "$phase" != "pre-apply" ]]; then
    [[ "$(jq -r '.bundle_revision_sha256 // empty' "$AUTHORIZATION_RECEIPT")" == "$BUNDLE_REVISION" ]] || die "v9 receipt bundle revision is not bound to live outputs"
    [[ "$(jq -r '.runtime_values_sha256 // empty' "$AUTHORIZATION_RECEIPT")" == "$VALUES_SHA256" ]] || die "v9 receipt runtime values hash is not bound"
  fi
  if [[ "$phase" == "pre-kubernetes" ]]; then
    [[ -n "$KUBERNETES_RENDER_SHA256" ]] || die "v9 receipt validation requires a render hash"
    jq -e --arg render "$KUBERNETES_RENDER_SHA256" '.render_sha256 == $render' "$AUTHORIZATION_RECEIPT" >/dev/null || die "v9 receipt render hash is not bound"
  fi
  CREATE_RECEIPT_VALIDATED=true
}

bind_create_receipt_runtime() {
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" ]] || return 0
  local updated
  updated="$(mktemp "${AUTHORIZATION_RECEIPT}.runtime.XXXXXX")" || die "could not allocate v9 receipt binding file"
  jq --arg bundle "$BUNDLE_REVISION" --arg values "$VALUES_SHA256" '.bundle_revision_sha256=$bundle | .runtime_values_sha256=$values' "$AUTHORIZATION_RECEIPT" >"$updated" || { rm -f -- "$updated"; die "v9 receipt runtime binding failed"; }
  chmod 0600 "$updated"
  mv -f -- "$updated" "$AUTHORIZATION_RECEIPT"
}

bind_create_receipt_render() {
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" ]] || return 0
  local updated
  updated="$(mktemp "${AUTHORIZATION_RECEIPT}.render.XXXXXX")" || die "could not allocate v9 render binding file"
  jq --arg render "$KUBERNETES_RENDER_SHA256" --arg bound "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '.render_sha256=$render | .render_bound_at=$bound' "$AUTHORIZATION_RECEIPT" >"$updated" || { rm -f -- "$updated"; die "v9 receipt render binding failed"; }
  chmod 0600 "$updated"
  mv -f -- "$updated" "$AUTHORIZATION_RECEIPT"
}

bind_repair_receipt_runtime() {
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]] || return 0
  local updated existing_bundle existing_values
  existing_bundle="$(jq -er '.bundle_revision_sha256' "$AUTHORIZATION_RECEIPT")" || die "repair receipt bundle binding is missing"
  [[ "$existing_bundle" == "$BUNDLE_REVISION" ]] || die "repair receipt bundle binding differs before runtime binding"
  existing_values="$(jq -r '.runtime_values_sha256 // empty' "$AUTHORIZATION_RECEIPT")"
  if [[ -n "$existing_values" ]]; then
    [[ "$existing_values" == "$VALUES_SHA256" ]] || die "repair receipt runtime binding differs before reuse"
    return 0
  fi
  updated="$(mktemp "${AUTHORIZATION_RECEIPT}.runtime.XXXXXX")" || die "could not allocate repair receipt binding file"
  jq --arg values "$VALUES_SHA256" '.runtime_values_sha256=$values' "$AUTHORIZATION_RECEIPT" >"$updated" || { rm -f -- "$updated"; die "repair receipt runtime binding failed"; }
  chmod 0600 "$updated"
  mv -f -- "$updated" "$AUTHORIZATION_RECEIPT"
}

bind_repair_receipt_render() {
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]] || return 0
  local updated
  updated="$(mktemp "${AUTHORIZATION_RECEIPT}.render.XXXXXX")" || die "could not allocate repair render binding file"
  jq --arg render "$KUBERNETES_RENDER_SHA256" --arg bound "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '.render_sha256=$render | .render_bound_at=$bound' "$AUTHORIZATION_RECEIPT" >"$updated" || { rm -f -- "$updated"; die "repair receipt render binding failed"; }
  chmod 0600 "$updated"
  mv -f -- "$updated" "$AUTHORIZATION_RECEIPT"
}

bind_autonomous_receipt_render() {
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-autonomous-authorization/v1" ]] || return 0
  local existing_render updated
  existing_render="$(jq -r '.render_sha256 // empty' "$AUTHORIZATION_RECEIPT")" || die "autonomous receipt render binding could not be read"
  if [[ -n "$existing_render" ]]; then
    [[ "$existing_render" == "$KUBERNETES_RENDER_SHA256" ]] || die "autonomous receipt render binding differs before reuse"
    return 0
  fi
  updated="$(mktemp "${AUTHORIZATION_RECEIPT}.render.XXXXXX")" || die "could not allocate autonomous receipt render binding file"
  jq --arg render "$KUBERNETES_RENDER_SHA256" --arg bound "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '.render_sha256=$render | .render_bound_at=$bound' "$AUTHORIZATION_RECEIPT" >"$updated" || { rm -f -- "$updated"; die "autonomous receipt render binding failed"; }
  chmod 0600 "$updated"
  mv -f -- "$updated" "$AUTHORIZATION_RECEIPT"
}

validate_repair_receipt() {
  local expected_render="${1:-}" expires expires_epoch expected_action scope repair_helper_sha smoke_helper_sha deployment_runner_sha actual_scope
  validate_plan_handoff
  [[ -n "$AUTHORIZATION_RECEIPT" ]] || die "v11 repair authorization receipt is required"
  [[ -f "$AUTHORIZATION_RECEIPT" && ! -L "$AUTHORIZATION_RECEIPT" ]] || die "v11 repair authorization receipt must be a regular file"
  [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]] || die "authorization receipt schema is not v11 repair-only"
  scope="$(jq -er '.repair_scope_sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$AUTHORIZATION_RECEIPT")" || die "v11 repair scope hash is missing"
  expected_action="APPLY DEV-EKS REPAIR-AND-RESUME $scope"
  actual_scope="$(jq -cjS '{manifest_sha256:.manifest_sha256,handoff_sha256:.handoff_sha256,account:.expected_account_id,region:.expected_region,run_id:.run_id,backend_config_sha256:.terraform_backend_config_sha256,capsule_sha256:.input_capsule_sha256,backend_image:.backend_image,backend_hostname:.backend_hostname,frontend_origin:.frontend_origin,bastion_instance_id:.bastion_instance_id,bastion_tags:.bastion_tags,cluster_name:.cluster_name,kubernetes_version:.kubernetes_version,kubernetes_version_status:.kubernetes_version_status,state_fingerprints:.state_fingerprints,retained_v9_run_id:.retained_v9_run_id,retained_v9_plan_sha256:.retained_v9_plan_sha256,monitoring_bucket:.monitoring_bucket,monitoring_prefix:.monitoring_prefix,bundle_revision_sha256:.bundle_revision_sha256,repair_helper_sha256:.repair_helper_sha256,smoke_helper_sha256:.smoke_helper_sha256,deployment_runner_sha256:.deployment_runner_sha256,kubectl_version:.kubectl_version,dev_eks_state_sha256:.dev_eks_state_sha256,dev_eks_state_lineage:.dev_eks_state_lineage,dev_eks_state_serial:.dev_eks_state_serial,actions:.permitted_actions}' "$AUTHORIZATION_RECEIPT" | sha256sum | awk '{print $1}')" || die "v11 repair scope could not be recomputed"
  [[ "$actual_scope" == "$scope" ]] || die "v11 repair scope does not match its bound receipt fields"
  repair_helper_sha="$(sha256sum "$REPAIR_BASTION_HELPER" | awk '{print $1}')"
  smoke_helper_sha="$(sha256sum "$REPAIR_SMOKE_HELPER" | awk '{print $1}')"
  deployment_runner_sha="$(sha256sum "$REPAIR_DEPLOYMENT_RUNNER" | awk '{print $1}')"
  jq -e --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg run "$RUN_ID" --arg backend "dev-eks/terraform.tfstate" --arg backend_config "$EXPECTED_BACKEND_CONFIG_SHA256" --arg capsule "$CAPSULE_SHA256" --arg capsule_path "$CAPSULE_REALPATH" --arg image "$BACKEND_IMAGE" --arg hostname "$BACKEND_HOSTNAME" --arg frontend "$FRONTEND_ORIGIN" --arg plan_id "$PLAN_ID" --argjson plan_version "$PLAN_VERSION" --arg manifest_sha "$PLAN_MANIFEST_SHA256" --arg manifest_path "$PLAN_MANIFEST_REALPATH" --arg handoff_path "$PLAN_HANDOFF_REALPATH" --arg handoff_sha "$PLAN_HANDOFF_SHA256" --arg action "$expected_action" --arg expected_render "$expected_render" --arg scope "$scope" --arg bastion "$BASTION_ID" --arg cluster "$CLUSTER_NAME" --arg target_version "$TARGET_KUBERNETES_VERSION" --arg bucket "$MONITORING_BUCKET" --arg prefix "$MONITORING_PREFIX" --arg bundle "$BUNDLE_REVISION" --arg retained_run "$RESUME_RUN_ID" --arg repair_helper "$repair_helper_sha" --arg smoke_helper "$smoke_helper_sha" --arg deployment_runner "$deployment_runner_sha" --arg state_sha "$DEV_EKS_STATE_SHA256" --arg lineage "$DEV_EKS_STATE_LINEAGE" --argjson serial "$DEV_EKS_STATE_SERIAL" '
    type == "object" and
    .schema_version == "dev-eks-repair-authorization/v1" and
    .handoff_schema_version == "plan-handoff/v1" and .manifest_schema_version == "plan-manifest/v3" and
    .plan_id == $plan_id and .plan_version == $plan_version and .manifest_sha256 == $manifest_sha and
    .manifest_path == $manifest_path and .handoff_path == $handoff_path and .handoff_sha256 == $handoff_sha and
    .status == "active" and .single_use == true and .run_id == $run and .expected_account_id == $account and .expected_region == $region and
    .terraform_backend_key == $backend and .terraform_backend_config_sha256 == $backend_config and
    .input_capsule_path == $capsule_path and .input_capsule_sha256 == $capsule and
    .backend_image == $image and .backend_hostname == $hostname and .frontend_origin == $frontend and
    .retained_v9_run_id == $retained_run and
    .bastion_instance_id == $bastion and .cluster_name == $cluster and
    .kubernetes_version == $target_version and .kubernetes_version_status == "STANDARD_SUPPORT" and
    (.bastion_tags | type == "object" and .Environment == "dev" and .Stack == "dev-eks" and .Phase == "eks-baseline" and .Project == "kdt-travelplanner" and .Name == "kdt-travelplanner-dev-eks-bastion") and
    .monitoring_bucket == $bucket and .monitoring_prefix == $prefix and .bundle_revision_sha256 == $bundle and
    .repair_helper_sha256 == $repair_helper and .smoke_helper_sha256 == $smoke_helper and
    ((.deployment_runner_sha256 == $deployment_runner) or (.completion_lease == true and .continuity_verified == true)) and .kubectl_version == "1.35.6" and
    .dev_eks_state_sha256 == $state_sha and .dev_eks_state_lineage == $lineage and .dev_eks_state_serial == $serial and
    (.state_fingerprints | type == "array" and length == 4 and (map(.key) | sort) == ["dev-eks/terraform.tfstate","dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"]) and
    (.protected_state_keys | type == "array" and sort == ["dev-eks/terraform.tfstate","dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"]) and
    (.permitted_actions | type == "array" and sort == ["repair existing Bastion kubectl in place","resume retained dev-eks Kubernetes deployment","retain existing resources and one owned Ingress ALB"]) and
    (.forbidden_actions | type == "array" and sort == ["Bastion replacement","Cloudflare mutation","IAM mutation","Kubernetes delete","Terraform plan/apply/destroy","protected State write","shared lifecycle cleanup"]) and
    (.paid_approval.status == "approved" and .paid_approval.action == $action and .paid_approval.scope_sha256 == $scope) and
    (((($expected_render | length) == 0) and (.render_sha256 == null or (.completion_lease == true and .continuity_verified == true and (.render_sha256 | type == "string" and test("^[0-9a-f]{64}$"))))) or (($expected_render | length) == 64 and .render_sha256 == $expected_render))
  ' "$AUTHORIZATION_RECEIPT" >/dev/null || die "v11 repair authorization receipt binding or approval is invalid"
  expires="$(jq -er '.expires_at | select(type == "string")' "$AUTHORIZATION_RECEIPT")" || die "v11 repair receipt expiry is missing"
  expires_epoch="$(parse_receipt_epoch "$expires")" || die "v11 repair receipt expiry is malformed"
  (( expires_epoch > $(date +%s) )) || die "v11 repair receipt is expired"
  if [[ -n "$BUNDLE_REVISION" ]]; then
    [[ "$(jq -r '.bundle_revision_sha256 // empty' "$AUTHORIZATION_RECEIPT")" == "$BUNDLE_REVISION" ]] || die "v11 repair receipt bundle revision is not bound to live outputs"
  fi
  if [[ -n "$VALUES_SHA256" ]]; then
    local receipt_values_sha
    receipt_values_sha="$(jq -r '.runtime_values_sha256 // empty' "$AUTHORIZATION_RECEIPT")"
    [[ -z "$receipt_values_sha" || "$receipt_values_sha" == "$VALUES_SHA256" ]] || die "v11 repair receipt runtime values hash is not bound"
  fi
  REPAIR_RECEIPT_VALIDATED=true
}

validate_v14_receipt() {
  local expected_render="${1:-}" expires expires_epoch
  validate_plan_handoff
  [[ -n "$AUTHORIZATION_RECEIPT" ]] || die "autonomous authorization receipt is required"
  jq -e --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg run "$(jq -r '.lifecycle_run_id' "$AUTHORIZATION_RECEIPT")" --arg manifest "$PLAN_MANIFEST_SHA256" --arg handoff "$PLAN_HANDOFF_REALPATH" --arg handoff_sha "$PLAN_HANDOFF_SHA256" --arg expected_render "$expected_render" --argjson version "$PLAN_VERSION" '
    type == "object" and
    .schema_version == "dev-eks-autonomous-authorization/v1" and
    .plan_id == "dev-eks-deployment-automation" and .plan_version == $version and
    .manifest_sha256 == $manifest and .handoff_path == $handoff and .handoff_sha256 == $handoff_sha and
    (.lifecycle_run_id | type == "string" and test("^[0-9]{8}T[0-9]{6}Z-[0-9]+$")) and
    .status == "active" and .single_use == true and
    (.expected_account_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    .expected_region == $region and .terraform_backend_key == "dev-eks/terraform.tfstate" and
    (.state_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.managed_address_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.managed_address_count | type == "number" and . >= 0 and floor == .) and
    (.runtime_values_sha256 == null or (.runtime_values_sha256 | type == "string" and test("^[0-9a-f]{64}$"))) and
    (.render_sha256 == null or (.render_sha256 | type == "string" and test("^[0-9a-f]{64}$"))) and
    (.protected_backends | type == "array" and sort == ["dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"]) and
    (.forbidden_actions | type == "array" and index("Terraform create/apply") != null and index("Cloudflare mutation") != null and index("destroy before full live success") != null) and
    (.permitted_actions | type == "array" and index("resume retained dev-eks Kubernetes deployment") != null and index("destroy exact dev-eks State only after frozen full success") != null) and
    (.full_live_success == false) and (.evidence_frozen == false) and (.destroy_armed == false) and
    ($expected_render == "" or .render_sha256 == $expected_render)
  ' "$AUTHORIZATION_RECEIPT" >/dev/null || die "autonomous authorization receipt schema or scope is invalid"
  expires="$(jq -er '.expires_at | select(type == "string")' "$AUTHORIZATION_RECEIPT")" || die "v14 authorization receipt expiry is missing"
  expires_epoch="$(parse_receipt_epoch "$expires")" || die "v14 authorization receipt expiry is malformed"
  (( expires_epoch > $(date +%s) )) || die "v14 authorization receipt is expired"
}

validate_authorization_receipt() {
  local expected_render="${1:-}" expires expires_epoch
  if [[ -n "$AUTHORIZATION_RECEIPT" ]] && jq -e '.schema_version == "dev-eks-autonomous-authorization/v1" and (.plan_version == 14 or .plan_version == 15)' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1; then
    validate_v14_receipt "$expected_render"
    return 0
  fi
  if [[ -n "$AUTHORIZATION_RECEIPT" ]] && jq -e '.schema_version == "dev-eks-repair-authorization/v1"' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1; then
    if [[ -n "$expected_render" ]]; then
      KUBERNETES_RENDER_SHA256="$expected_render"
      validate_repair_receipt "$expected_render"
    else
      validate_repair_receipt
    fi
    return 0
  fi
  if [[ -n "$AUTHORIZATION_RECEIPT" ]] && jq -e '.schema_version == "dev-eks-create-authorization/v1"' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1; then
    if [[ -n "$expected_render" ]]; then
      KUBERNETES_RENDER_SHA256="$expected_render"
      validate_create_receipt pre-kubernetes
    else
      validate_create_receipt prepared
    fi
    return 0
  fi
  [[ -n "$AUTHORIZATION_RECEIPT" ]] || return 0
  [[ "$MODE" == "resume" && "$SKIP_TERRAFORM_APPLY" == true ]] || die "legacy v7 authorization receipt is valid only for --mode resume --skip-terraform-apply"
  jq -e \
    'type == "object"
     and .schema_version == "dev-eks-autonomous-authorization/v1"
     and .plan_id == "dev-eks-deployment-automation"
     and .plan_version == 7
     and .manifest_sha256 == "d3a35fe33b73a0d5d22af5b21f44d36caa8f447831ecca3977043e5637806e67"
     and (.lifecycle_run_id | type == "string" and test("^[0-9]{8}T[0-9]{6}Z-[0-9]+$"))
     and .status == "active"
     and .single_use == true
     and (.expected_account_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
     and .expected_region == "ap-northeast-2"
     and .terraform_backend_key == "dev-eks/terraform.tfstate"
     and (.state_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
     and (.managed_address_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
     and (.managed_address_count | type == "number" and . >= 0 and floor == .)
     and (.runtime_values_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
     and (.render_sha256 == null or (.render_sha256 | type == "string" and test("^[0-9a-f]{64}$")))
     and (.protected_backends | type == "array" and (index("dev/terraform.tfstate") != null) and (index("dev-runtime/terraform.tfstate") != null) and (index("dev-load-test/terraform.tfstate") != null))
     and (.forbidden_actions | type == "array" and (index("Terraform create/apply") != null) and (index("Cloudflare mutation") != null))' \
    "$AUTHORIZATION_RECEIPT" >/dev/null || die "authorization receipt schema or scope is invalid"
  expires="$(jq -er '.expires_at | select(type == "string")' "$AUTHORIZATION_RECEIPT")" || die "authorization receipt expiry is missing"
  expires_epoch="$(parse_receipt_epoch "$expires")" || die "authorization receipt expiry is malformed"
  (( expires_epoch > $(date +%s) )) || die "authorization receipt is expired"
  if [[ -n "$expected_render" ]]; then
    jq -e --arg expected "$expected_render" '.render_sha256 == $expected' "$AUTHORIZATION_RECEIPT" >/dev/null || die "authorization receipt render hash does not match the actual render"
  else
    jq -e '.render_sha256 == null' "$AUTHORIZATION_RECEIPT" >/dev/null || die "authorization receipt was already render-bound before prepare"
  fi
}

confirm_exact() {
  local expected="$1"
  if [[ "$NON_INTERACTIVE" == true ]]; then
    if [[ -n "$AUTHORIZATION_RECEIPT" ]] && jq -e '.schema_version == "dev-eks-autonomous-authorization/v1" and (.plan_version == 14 or .plan_version == 15)' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1; then
      [[ "$expected" == APPLY\ TERRAFORM\ * || "$expected" == APPLY\ KUBERNETES\ * ]] || die "v14 receipt does not authorize this non-interactive action"
      if [[ "$expected" == APPLY\ KUBERNETES\ * ]]; then
        validate_v14_receipt "${expected#APPLY KUBERNETES }"
      else
        validate_v14_receipt
      fi
    elif [[ -n "$AUTHORIZATION_RECEIPT" ]] && jq -e '.schema_version == "dev-eks-create-authorization/v1"' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1; then
      if [[ "$expected" == APPLY\ TERRAFORM\ * ]]; then
        validate_create_receipt pre-apply
      elif [[ "$expected" == APPLY\ KUBERNETES\ * ]]; then
        validate_create_receipt pre-kubernetes
      else
        die "v9 receipt does not authorize this non-interactive action"
      fi
    elif [[ -n "$AUTHORIZATION_RECEIPT" ]] && jq -e '.schema_version == "dev-eks-repair-authorization/v1"' "$AUTHORIZATION_RECEIPT" >/dev/null 2>&1; then
      [[ "$expected" == APPLY\ KUBERNETES\ * ]] || die "v10 repair receipt does not authorize this non-interactive action"
      validate_repair_receipt "${expected#APPLY KUBERNETES }"
    elif [[ "$MODE" == "run" || "$MODE" == "resume" ]] && [[ -n "$INPUT_CAPSULE_PATH" ]]; then
      die "non-interactive mutation requires a v9 authorization receipt"
    fi
    return 0
  fi
  local response
  printf '%s\n' "Type exactly: $expected" >&2
  IFS= read -r response
  [[ "$response" == "$expected" ]] || die "exact approval was not confirmed"
}

terraform_apply_if_needed() {
  if [[ "$SKIP_TERRAFORM_APPLY" == true ]]; then
    return 0
  fi
  [[ -n "$PLAN_SNAPSHOT" ]] || validate_saved_plan
  confirm_exact "APPLY TERRAFORM $TERRAFORM_PLAN_SHA256"
  local snapshot_after_approval
  snapshot_after_approval="$(sha256sum "$PLAN_SNAPSHOT" | awk '{print $1}')"
  [[ "$snapshot_after_approval" == "$TERRAFORM_PLAN_SHA256" ]] || die "private Terraform plan snapshot changed after approval"
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" ]]; then
    capture_protected_state_fingerprints "$REPORT_ROOT/protected-states-before.private.json"
  fi
  APPLY_STARTED=true
  LAST_STAGE="terraform_apply"
  log_event "terraform_apply" "started"
  terraform_with_auth -chdir="$TERRAFORM_ROOT" apply -input=false "$PLAN_SNAPSHOT" >>"$LOG_FILE" 2>&1 || die "terraform apply failed"
  log_event "terraform_apply" "succeeded"
  POST_PLAN="$(mktemp "${TMPDIR:-/tmp}/dev-eks-post-apply.XXXXXX")" || die "could not allocate post-apply plan file"
  set +e
  terraform_with_auth -chdir="$TERRAFORM_ROOT" plan -input=false -detailed-exitcode -out="$POST_PLAN" >>"$LOG_FILE" 2>&1
  local plan_status=$?
  set -e
  [[ "$plan_status" -eq 0 ]] || die "post-apply detailed plan is not clean"
  log_event "terraform_post_apply_plan" "clean"
  load_runtime_outputs
  verify_infrastructure_readiness
  capture_protected_state_fingerprints
  compare_protected_state_fingerprints
}

load_runtime_outputs() {
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    load_repair_state_outputs
    VPC_ID="$(repair_state_output vpc_id)"
    PUBLIC_SUBNET_IDS="$(repair_state_output public_subnet_ids)"
    API_CERTIFICATE_ARN="$(repair_state_output api_certificate_arn)"
    MONITORING_BUCKET="$(repair_state_output monitoring_config_bucket_name)"
    MONITORING_PREFIX="$(repair_state_output monitoring_bundle_prefix)"
    BUNDLE_REVISION="$(repair_state_output monitoring_bundle_revision)"
    CONTRACT_KEY="$(repair_state_output deployment_contract_s3_key)"
    CONTRACT_SHA256="$(repair_state_output deployment_contract_sha256)"
    BASTION_ID="$(repair_state_output bastion_instance_id)"
    CLUSTER_NAME="$(repair_state_output cluster_name)"
    NODE_GROUP_NAME="$(repair_state_output node_group_name)"
    DATABASE_IDENTIFIER="$(repair_state_output database_identifier)"
    REDIS_REPLICATION_GROUP_ID="$(repair_state_output redis_replication_group_id)"
    REDIS_ENDPOINT="$(repair_state_output redis_primary_endpoint)"
    REDIS_PORT="$(repair_state_output redis_port)"
    REDIS_SECRET_ARN="$(repair_state_output redis_auth_secret_arn)"
    PROFILE_IMAGE_BUCKET="$(repair_state_output profile_image_bucket_name)"
    PROFILE_IMAGE_PUBLIC_BASE_URL="$(repair_state_output profile_image_public_base_url)"
    MONITORING_INSTANCE_ID="$(repair_state_output monitoring_instance_id)"
    MONITORING_DNS="$(repair_state_output monitoring_private_dns_name)"
  else
    VPC_ID="$(tf_output vpc_id)"
    PUBLIC_SUBNET_IDS="$(tf_output public_subnet_ids)"
    API_CERTIFICATE_ARN="$(tf_output api_certificate_arn)"
    MONITORING_BUCKET="$(tf_output monitoring_config_bucket_name)"
    MONITORING_PREFIX="$(tf_output monitoring_bundle_prefix)"
    BUNDLE_REVISION="$(tf_output monitoring_bundle_revision)"
    CONTRACT_KEY="$(tf_output deployment_contract_s3_key)"
    CONTRACT_SHA256="$(tf_output deployment_contract_sha256)"
    BASTION_ID="$(tf_output bastion_instance_id)"
    CLUSTER_NAME="$(tf_output cluster_name)"
    NODE_GROUP_NAME="$(tf_output node_group_name)"
    DATABASE_IDENTIFIER="$(tf_output database_identifier)"
    REDIS_REPLICATION_GROUP_ID="$(tf_output redis_replication_group_id)"
    REDIS_ENDPOINT="$(tf_output redis_primary_endpoint)"
    REDIS_PORT="$(tf_output redis_port)"
    REDIS_SECRET_ARN="$(tf_output redis_auth_secret_arn)"
    PROFILE_IMAGE_BUCKET="$(tf_output profile_image_bucket_name)"
    PROFILE_IMAGE_PUBLIC_BASE_URL="$(tf_output profile_image_public_base_url)"
    MONITORING_INSTANCE_ID="$(tf_output monitoring_instance_id)"
    MONITORING_DNS="$(tf_output monitoring_private_dns_name)"
  fi
  [[ "$BUNDLE_REVISION" =~ ^[0-9a-f]{64}$ ]] || die "Terraform bundle revision output is invalid"
  [[ "$CONTRACT_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "Terraform contract checksum output is invalid"
  [[ "$MONITORING_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die "Terraform monitoring bucket output is invalid"
  [[ "$VPC_ID" =~ ^vpc-[0-9a-f]+$ ]] || die "Terraform VPC output is invalid"
  jq -e 'type == "array" and length >= 2 and all(.[]; type == "string")' <<<"$PUBLIC_SUBNET_IDS" >/dev/null || die "Terraform public subnet output is invalid"
  [[ "$API_CERTIFICATE_ARN" =~ ^arn:aws:acm:${REGION}:${EXPECTED_ACCOUNT_ID}:certificate/.+$ ]] || die "Terraform ACM certificate output is invalid"
  [[ "$MONITORING_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$ && "$MONITORING_PREFIX" != *".."* && "$MONITORING_PREFIX" != *"//"* ]] || die "Terraform bundle prefix output is invalid"
  [[ "$CONTRACT_KEY" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$ && "$CONTRACT_KEY" != *".."* && "$CONTRACT_KEY" != *"//"* ]] || die "Terraform contract key output is invalid"
  [[ "$BASTION_ID" =~ ^i-[0-9a-f]+$ ]] || die "Terraform Bastion instance output is invalid"
  [[ "$CLUSTER_NAME" =~ ^[a-z0-9][a-z0-9-]{0,99}$ ]] || die "Terraform cluster name output is invalid"
  [[ "$NODE_GROUP_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$ ]] || die "Terraform node group output is invalid"
  [[ "$DATABASE_IDENTIFIER" =~ ^[a-zA-Z][a-zA-Z0-9-]{0,62}$ ]] || die "Terraform database identifier output is invalid"
  [[ "$REDIS_REPLICATION_GROUP_ID" =~ ^[a-zA-Z][a-zA-Z0-9-]{0,62}$ ]] || die "Terraform Redis replication group output is invalid"
  [[ "$REDIS_ENDPOINT" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "Terraform Redis endpoint output is invalid"
  [[ "$REDIS_PORT" =~ ^[0-9]+$ && "$REDIS_PORT" -ge 1 && "$REDIS_PORT" -le 65535 ]] || die "Terraform Redis port output is invalid"
  [[ "$REDIS_SECRET_ARN" =~ ^arn:aws:secretsmanager:${REGION}:${EXPECTED_ACCOUNT_ID}:secret:.+$ ]] || die "Terraform Redis secret ARN output is invalid"
  [[ "$PROFILE_IMAGE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die "Terraform profile image bucket output is invalid"
  [[ "$MONITORING_INSTANCE_ID" =~ ^i-[0-9a-f]+$ ]] || die "Terraform Monitoring instance output is invalid"
  [[ "$MONITORING_DNS" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "Terraform Monitoring DNS output is invalid"
  if [[ -n "$INPUT_CAPSULE_PATH" ]]; then
    jq -e --arg vpc "$VPC_ID" --arg cert "$API_CERTIFICATE_ARN" --argjson subnets "$PUBLIC_SUBNET_IDS" '
      .vpc_id == $vpc and .api_certificate_arn == $cert and
      ((.public_subnet_ids | sort) == ($subnets | sort))
    ' "$INPUT_CAPSULE_PATH" >/dev/null || die "Terraform network or ACM outputs do not match the action-values capsule"
  fi
}

upload_action_values() {
  VALUES_KEY="$MONITORING_PREFIX/runs/$RUN_ID/action-values.json"
  log_event "action_values_upload" "started"
  aws "${aws_args[@]}" s3 cp "$VALUES_FILE" "s3://$MONITORING_BUCKET/$VALUES_KEY" --sse AES256 >>"$LOG_FILE" 2>&1 || die "action-time values upload failed"
  log_event "action_values_upload" "succeeded"
}

persist_ssm_failure() {
  local invocation="$1" status="$2" response_code safe_reason
  response_code="$(jq -r '.ResponseCode // null' <<<"$invocation" 2>/dev/null || printf 'null')"
  safe_reason="$(jq -r '.StandardErrorContent // ""' <<<"$invocation" 2>/dev/null | sed -n '1p')"
  if [[ ! "$safe_reason" =~ ^stage=[a-z0-9-]+[[:space:]]status=failed[[:space:]]reason=[A-Za-z0-9_.:-]+([[:space:]][A-Za-z0-9_.:-]+)*$ ]]; then
    safe_reason="remote SSM stage returned terminal status $status"
  fi
  jq -n --arg stage "$LAST_STAGE" --arg status "$status" --arg command_id "$(jq -r '.CommandId // ""' <<<"$invocation")" --arg instance_id "$(jq -r '.InstanceId // ""' <<<"$invocation")" --arg reason "$safe_reason" --argjson response_code "$response_code" '{schema_version:"dev-eks-ssm-failure/v1",stage:$stage,status:$status,response_code:$response_code,command_id:$command_id,instance_id:$instance_id,safe_reason:$reason}' >"$REPORT_ROOT/${LAST_STAGE}-ssm-failure.private.json" || die "SSM failure evidence could not be written"
  chmod 0600 "$REPORT_ROOT/${LAST_STAGE}-ssm-failure.private.json" || die "SSM failure evidence permissions could not be set"
}

poll_ssm() {
  local command_id="$1" status="" deadline=$((SECONDS + SSM_TIMEOUT_SECONDS)) invocation="" poll_error_file="$REPORT_ROOT/ssm-poll.stderr"
  while ((SECONDS < deadline)); do
    if ! invocation="$(aws "${aws_args[@]}" ssm get-command-invocation --command-id "$command_id" --instance-id "$BASTION_ID" --output json 2>"$poll_error_file")"; then
      cat "$poll_error_file" >>"$LOG_FILE"
      if grep -Eqi 'AccessDenied|UnauthorizedOperation|not authorized|AccessDeniedException' "$poll_error_file"; then
        persist_ssm_failure '{"CommandId":"'"$command_id"'","InstanceId":"'"$BASTION_ID"'","ResponseCode":null}' "AccessDenied"
        die "SSM invocation lookup was denied by IAM"
      fi
      if grep -q "InvocationDoesNotExist" "$poll_error_file"; then
        log_event "ssm_poll" "transient_invocation_not_visible"
        sleep 5
        continue
      fi
      die "SSM invocation lookup failed"
    fi
    if ! jq -e --arg command_id "$command_id" --arg instance_id "$BASTION_ID" '
      type == "object"
      and .CommandId == $command_id
      and .InstanceId == $instance_id
      and (.Status | type == "string")
      and (.StandardOutputContent == null or (.StandardOutputContent | type == "string"))
      and (.StandardErrorContent == null or (.StandardErrorContent | type == "string"))
    ' <<<"$invocation" >/dev/null 2>>"$LOG_FILE"; then
      die "SSM invocation response schema is invalid"
    fi
    if ! status="$(jq -er '.Status | select(type == "string")' <<<"$invocation" 2>>"$LOG_FILE")"; then
      die "SSM invocation response schema is invalid"
    fi
    case "$status" in
      Success)
        jq -e '(.ResponseCode | type == "number") and (.ResponseCode == (.ResponseCode | floor)) and .ResponseCode == 0' <<<"$invocation" >/dev/null 2>>"$LOG_FILE" || die "SSM invocation success response is invalid"
        printf '%s' "$invocation"
        return 0
        ;;
      Failed|Cancelled|TimedOut|Cancelling)
        persist_ssm_failure "$invocation" "$status"
        die "SSM stage failed with status $status" ;;
      Pending|InProgress|Delayed) ;;
      *) die "SSM invocation status is unknown" ;;
    esac
    sleep 5
  done
  die "SSM polling timeout"
}

run_remote_stage() {
  local stage="$1" approved_render="${2:-}" command_id invocation output ssm_parameters
  local remote_work_dir="/var/tmp/travel-planner-dev-eks-${REMOTE_RUN_ID}"
  local remote_runner="$remote_work_dir/run-dev-eks-deployment.sh"
  local remote_manifest="$remote_work_dir/bundle-manifest.json"
  local manifest_uri="s3://${MONITORING_BUCKET}/${MONITORING_PREFIX}/bundle-manifest.json"
  local bundle_uri="s3://${MONITORING_BUCKET}/${MONITORING_PREFIX}/scripts/eks/run-dev-eks-deployment.sh"
  local runner_uri="$bundle_uri" runner_sha="" repair_runner_key="" compatibility_runner_key=""
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    [[ -f "$REPAIR_DEPLOYMENT_RUNNER" && ! -L "$REPAIR_DEPLOYMENT_RUNNER" ]] || die "repair deployment runner is unavailable"
    runner_sha="$(sha256sum "$REPAIR_DEPLOYMENT_RUNNER" | awk '{print $1}')"
    repair_runner_key="$MONITORING_PREFIX/runs/$RUN_ID/repair/run-dev-eks-deployment.sh"
    if [[ "${REPAIR_DEPLOYMENT_RUNNER_UPLOADED:-false}" != true ]]; then
      aws "${aws_args[@]}" s3 cp "$REPAIR_DEPLOYMENT_RUNNER" "s3://$MONITORING_BUCKET/$repair_runner_key" --sse AES256 >>"$LOG_FILE" 2>&1 || die "repair deployment runner upload failed"
      REPAIR_DEPLOYMENT_RUNNER_UPLOADED=true
    fi
    runner_uri="s3://$MONITORING_BUCKET/$repair_runner_key"
  else
    # The retained immutable bundle predates the explicit KUBECONFIG path and
    # the v14 workload/RBAC compatibility repairs.  Transport the corrected
    # runner through a run-scoped, SHA-verified object; do not mutate the
    # Terraform-managed immutable bundle or perform a Terraform apply.
    [[ -f "$REPAIR_DEPLOYMENT_RUNNER" && ! -L "$REPAIR_DEPLOYMENT_RUNNER" ]] || die "compatibility deployment runner is unavailable"
    runner_sha="$(sha256sum "$REPAIR_DEPLOYMENT_RUNNER" | awk '{print $1}')"
    compatibility_runner_key="$MONITORING_PREFIX/runs/$RUN_ID/compat/run-dev-eks-deployment.sh"
    if [[ "$DEPLOYMENT_RUNNER_UPLOADED" != true ]]; then
      aws "${aws_args[@]}" s3 cp "$REPAIR_DEPLOYMENT_RUNNER" "s3://$MONITORING_BUCKET/$compatibility_runner_key" --sse AES256 >>"$LOG_FILE" 2>&1 || die "compatibility deployment runner upload failed"
      DEPLOYMENT_RUNNER_UPLOADED=true
    fi
    runner_uri="s3://$MONITORING_BUCKET/$compatibility_runner_key"
  fi
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    printf -v command 'set -eu; mkdir -p %q; chmod 700 %q; aws s3 cp %q %q; jq -e --arg expected %q '\''.schema_version == "dev-eks-bundle/v1" and .revision == $expected'\'' %q >/dev/null; test "$(jq -cjS '\''.files'\'' %q | sha256sum | awk '\''{print $1}'\'')" = %q; aws s3 cp %q %q; test "$(sha256sum %q | awk '\''{print $1}'\'')" = %q; chmod 700 %q; bash %q --stage %q --bucket %q --bundle-prefix %q --contract-key %q --values-s3-key %q --expected-bundle-revision %q --expected-contract-sha256 %q --expected-values-sha256 %q --expected-account-id %q --expected-region %q --redis-primary-endpoint %q --work-dir %q' \
      "$remote_work_dir" "$remote_work_dir" "$manifest_uri" "$remote_manifest" "$BUNDLE_REVISION" "$remote_manifest" "$remote_manifest" "$BUNDLE_REVISION" "$runner_uri" "$remote_runner" "$remote_runner" "$runner_sha" "$remote_runner" "$remote_runner" "$stage" "$MONITORING_BUCKET" "$MONITORING_PREFIX" "$CONTRACT_KEY" "$VALUES_KEY" "$BUNDLE_REVISION" "$CONTRACT_SHA256" "$VALUES_SHA256" "$EXPECTED_ACCOUNT_ID" "$REGION" "$REDIS_ENDPOINT" "$remote_work_dir"
  else
    printf -v command 'set -eu; mkdir -p %q; chmod 700 %q; aws s3 cp %q %q; jq -e --arg expected %q '\''.schema_version == "dev-eks-bundle/v1" and .revision == $expected'\'' %q >/dev/null; test "$(jq -cjS '\''.files'\'' %q | sha256sum | awk '\''{print $1}'\'')" = %q; aws s3 cp %q %q; test "$(sha256sum %q | awk '\''{print $1}'\'')" = %q; chmod 700 %q; bash %q --stage %q --bucket %q --bundle-prefix %q --contract-key %q --values-s3-key %q --expected-bundle-revision %q --expected-contract-sha256 %q --expected-values-sha256 %q --expected-account-id %q --expected-region %q --redis-primary-endpoint %q --work-dir %q' \
      "$remote_work_dir" "$remote_work_dir" "$manifest_uri" "$remote_manifest" "$BUNDLE_REVISION" "$remote_manifest" "$remote_manifest" "$BUNDLE_REVISION" "$runner_uri" "$remote_runner" "$remote_runner" "$runner_sha" "$remote_runner" "$remote_runner" "$stage" "$MONITORING_BUCKET" "$MONITORING_PREFIX" "$CONTRACT_KEY" "$VALUES_KEY" "$BUNDLE_REVISION" "$CONTRACT_SHA256" "$VALUES_SHA256" "$EXPECTED_ACCOUNT_ID" "$REGION" "$REDIS_ENDPOINT" "$remote_work_dir"
  fi
  printf -v command 'export AWS_REGION=%q AWS_DEFAULT_REGION=%q; %s' "$REGION" "$REGION" "$command"
  if [[ -n "$approved_render" ]]; then
    printf -v command '%s --expected-render-sha256 %q' "$command" "$approved_render"
  fi
  if ! ssm_parameters="$(jq -cn --arg command "$command" '{commands: [$command]}')"; then
    die "SSM command parameters could not be serialized"
  fi
  jq -e 'type == "object" and (.commands | type == "array") and (.commands | length == 1) and (.commands[0] | type == "string" and length > 0)' <<<"$ssm_parameters" >/dev/null 2>>"$LOG_FILE" || die "SSM command parameters have invalid JSON shape"
  log_event "ssm_${stage}" "submitting"
  command_id="$(aws "${aws_args[@]}" ssm send-command --document-name AWS-RunShellScript --instance-ids "$BASTION_ID" --parameters "$ssm_parameters" --comment "dev-eks-${RUN_ID}-${stage}" --query Command.CommandId --output text 2>>"$LOG_FILE")" || die "SSM command submission failed"
  [[ "$command_id" =~ ^[A-Za-z0-9-]{36}$ ]] || die "SSM command submission returned invalid command id"
  log_event "ssm_${stage}" "submitted"
  invocation="$(poll_ssm "$command_id")"
  output="$(jq -r '.StandardOutputContent // ""' <<<"$invocation")"
  printf '%s\n' "$output" >"$REPORT_ROOT/${stage}-stdout.txt"
  jq -r '.StandardErrorContent // ""' <<<"$invocation" >"$REPORT_ROOT/${stage}-stderr.txt"
  log_event "ssm_${stage}" "succeeded"
  printf '%s' "$invocation"
}

run_remote_smoke() {
  local smoke_helper_key="$MONITORING_PREFIX/runs/$RUN_ID/smoke/run-dev-eks-lifecycle-remote.sh"
  local smoke_script_key="$MONITORING_PREFIX/runs/$RUN_ID/smoke/verify-eks-observability-smoke.py"
  local helper_sha smoke_sha remote_work_dir command command_id invocation ssm_parameters output
  [[ -f "$LIFECYCLE_REMOTE_HELPER" && ! -L "$LIFECYCLE_REMOTE_HELPER" ]] || die "smoke helper is unavailable"
  [[ -f "$SMOKE_VERIFIER" && ! -L "$SMOKE_VERIFIER" ]] || die "observability smoke verifier is unavailable"
  helper_sha="$(sha256sum "$LIFECYCLE_REMOTE_HELPER" | awk '{print $1}')"
  smoke_sha="$(sha256sum "$SMOKE_VERIFIER" | awk '{print $1}')"
  aws "${aws_args[@]}" s3 cp "$LIFECYCLE_REMOTE_HELPER" "s3://$MONITORING_BUCKET/$smoke_helper_key" --sse AES256 >>"$LOG_FILE" 2>&1 || die "smoke helper upload failed"
  aws "${aws_args[@]}" s3 cp "$SMOKE_VERIFIER" "s3://$MONITORING_BUCKET/$smoke_script_key" --sse AES256 >>"$LOG_FILE" 2>&1 || die "observability smoke verifier upload failed"
  remote_work_dir="/var/tmp/travel-planner-dev-eks-${REMOTE_RUN_ID}/smoke"
  printf -v command 'set -eu; mkdir -p %q; chmod 700 %q; export AWS_REGION=%q AWS_DEFAULT_REGION=%q; aws s3 cp %q %q; test "$(sha256sum %q | awk '\''{print $1}'\'')" = %q; aws s3 cp %q %q; test "$(sha256sum %q | awk '\''{print $1}'\'')" = %q; chmod 700 %q %q; bash %q --stage smoke --cluster-name %q --region %q --bucket %q --smoke-script-key %q --expected-smoke-script-sha256 %q --backend-hostname %q --monitoring-dns %q --ingress-group kdt-travelplanner-dev-eks --expected-helper-sha256 %q --database-identifier %q --redis-replication-group-id %q --redis-endpoint %q --redis-port %q --redis-secret-arn %q --profile-image-bucket %q --work-dir %q' \
    "$remote_work_dir" "$remote_work_dir" "$REGION" "$REGION" "s3://$MONITORING_BUCKET/$smoke_helper_key" "$remote_work_dir/run-dev-eks-lifecycle-remote.sh" "$remote_work_dir/run-dev-eks-lifecycle-remote.sh" "$helper_sha" "s3://$MONITORING_BUCKET/$smoke_script_key" "$remote_work_dir/verify-eks-observability-smoke.py" "$remote_work_dir/verify-eks-observability-smoke.py" "$smoke_sha" "$remote_work_dir/run-dev-eks-lifecycle-remote.sh" "$remote_work_dir/verify-eks-observability-smoke.py" "$remote_work_dir/run-dev-eks-lifecycle-remote.sh" "$CLUSTER_NAME" "$REGION" "$MONITORING_BUCKET" "$smoke_script_key" "$smoke_sha" "$BACKEND_HOSTNAME" "$MONITORING_DNS" "$helper_sha" "$DATABASE_IDENTIFIER" "$REDIS_REPLICATION_GROUP_ID" "$REDIS_ENDPOINT" "$REDIS_PORT" "$REDIS_SECRET_ARN" "$PROFILE_IMAGE_BUCKET" "$remote_work_dir"
  if ! ssm_parameters="$(jq -cn --arg command "$command" '{commands: [$command]}')"; then
    die "smoke SSM command parameters could not be serialized"
  fi
  jq -e 'type == "object" and (.commands | type == "array") and (.commands | length == 1) and (.commands[0] | type == "string" and length > 0)' <<<"$ssm_parameters" >/dev/null 2>>"$LOG_FILE" || die "smoke SSM command parameters have invalid JSON shape"
  log_event "ssm_smoke" "submitting"
  command_id="$(aws "${aws_args[@]}" ssm send-command --document-name AWS-RunShellScript --instance-ids "$BASTION_ID" --parameters "$ssm_parameters" --comment "dev-eks-${RUN_ID}-smoke" --query Command.CommandId --output text 2>>"$LOG_FILE")" || die "smoke SSM command submission failed"
  [[ "$command_id" =~ ^[A-Za-z0-9-]{36}$ ]] || die "smoke SSM command submission returned invalid command id"
  invocation="$(poll_ssm "$command_id")"
  output="$(jq -r '.StandardOutputContent // ""' <<<"$invocation")"
  printf '%s\n' "$output" >"$REPORT_ROOT/smoke-stdout.txt"
  jq -r '.StandardErrorContent // ""' <<<"$invocation" >"$REPORT_ROOT/smoke-stderr.txt"
  grep -qx 'stage=smoke status=success' "$REPORT_ROOT/smoke-stdout.txt" || die "observability smoke did not report success"
  jq -n --arg helper "$helper_sha" --arg verifier "$smoke_sha" '{schema_version:"observability-smoke/v1",status:"success",remote_helper_sha256:$helper,verifier_sha256:$verifier,secret_key_count:9,dns_independent_https:true}' >"$REPORT_ROOT/observability-smoke.redacted.json" || die "observability smoke evidence write failed"
  chmod 0600 "$REPORT_ROOT/observability-smoke.redacted.json" "$REPORT_ROOT/smoke-stdout.txt" "$REPORT_ROOT/smoke-stderr.txt"
  log_event "ssm_smoke" "succeeded"
}

run_repair_remote_smoke() {
  local smoke_key="${MONITORING_PREFIX}/runs/${RUN_ID}/repair-smoke/run-dev-eks-repair-smoke.sh"
  local helper_sha expected_helper_sha remote_work_dir command command_id invocation ssm_parameters output
  [[ -f "$REPAIR_SMOKE_HELPER" && ! -L "$REPAIR_SMOKE_HELPER" ]] || die "repair smoke helper is unavailable"
  helper_sha="$(sha256sum "$REPAIR_SMOKE_HELPER" | awk '{print $1}')"
  expected_helper_sha="$(jq -er '.smoke_helper_sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$AUTHORIZATION_RECEIPT")" || die "repair receipt smoke helper checksum is missing"
  [[ "$helper_sha" == "$expected_helper_sha" ]] || die "repair smoke helper checksum does not match the authorized preflight"
  aws "${aws_args[@]}" s3 cp "$REPAIR_SMOKE_HELPER" "s3://$MONITORING_BUCKET/$smoke_key" --sse AES256 >>"$LOG_FILE" 2>&1 || die "repair smoke helper upload failed"
  remote_work_dir="/var/tmp/travel-planner-dev-eks-${REMOTE_RUN_ID}/repair-smoke"
  printf -v command 'set -eu; mkdir -p %q; chmod 700 %q; export AWS_REGION=%q AWS_DEFAULT_REGION=%q; aws s3 cp %q %q; test "$(sha256sum %q | awk '\''{print $1}'\'')" = %q; chmod 700 %q; bash %q --cluster-name %q --region %q --backend-hostname %q --monitoring-dns %q --redis-endpoint %q --redis-port %q --work-dir %q' \
    "$remote_work_dir" "$remote_work_dir" "$REGION" "$REGION" "s3://$MONITORING_BUCKET/$smoke_key" "$remote_work_dir/run-dev-eks-repair-smoke.sh" "$remote_work_dir/run-dev-eks-repair-smoke.sh" "$helper_sha" "$remote_work_dir/run-dev-eks-repair-smoke.sh" "$remote_work_dir/run-dev-eks-repair-smoke.sh" "$CLUSTER_NAME" "$REGION" "$BACKEND_HOSTNAME" "$MONITORING_DNS" "$REDIS_ENDPOINT" "$REDIS_PORT" "$remote_work_dir"
  ssm_parameters="$(jq -cn --arg command "$command" '{commands: [$command]}')" || die "repair smoke SSM parameters could not be serialized"
  jq -e 'type == "object" and (.commands | type == "array") and (.commands | length == 1) and (.commands[0] | type == "string" and length > 0)' <<<"$ssm_parameters" >/dev/null || die "repair smoke SSM parameters shape is invalid"
  log_event "ssm_repair_smoke" "submitting"
  command_id="$(aws "${aws_args[@]}" ssm send-command --document-name AWS-RunShellScript --instance-ids "$BASTION_ID" --parameters "$ssm_parameters" --comment "dev-eks-${RUN_ID}-repair-smoke" --query Command.CommandId --output text 2>>"$LOG_FILE")" || die "repair smoke SSM command submission failed"
  [[ "$command_id" =~ ^[A-Za-z0-9-]{36}$ ]] || die "repair smoke SSM command id is invalid"
  LAST_STAGE="repair-smoke"
  invocation="$(poll_ssm "$command_id")"
  output="$(jq -r '.StandardOutputContent // ""' <<<"$invocation")"
  printf '%s\n' "$output" >"$REPORT_ROOT/repair-smoke-stdout.txt"
  jq -r '.StandardErrorContent // ""' <<<"$invocation" >"$REPORT_ROOT/repair-smoke-stderr.txt"
  grep -qx 'stage=repair-smoke status=success' "$REPORT_ROOT/repair-smoke-stdout.txt" || die "repair smoke did not report success"
  jq -n --arg helper "$helper_sha" --arg cname "$INGRESS_CNAME_TARGET" '{schema_version:"dev-eks-repair-smoke/v1",status:"success",helper_sha256:$helper,ingress_hostname:$cname,bastion_private_checks:true}' >"$REPORT_ROOT/repair-smoke.redacted.json" || die "repair smoke evidence write failed"
  chmod 0600 "$REPORT_ROOT/repair-smoke.redacted.json" "$REPORT_ROOT/repair-smoke-stdout.txt" "$REPORT_ROOT/repair-smoke-stderr.txt"
  log_event "ssm_repair_smoke" "succeeded"
}

run_operator_native_smoke() {
  local lb_json lb_count lb_arn tag_json target_groups tg target_health all_healthy
  local rds_status redis_status deadline profile_bucket
  [[ "$INGRESS_CNAME_TARGET" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]] || die "validated Ingress hostname is missing before native smoke"
  lb_json="$(aws "${aws_args[@]}" elbv2 describe-load-balancers --query "LoadBalancers[?DNSName=='$INGRESS_CNAME_TARGET']" --output json 2>>"$LOG_FILE")" || die "native ALB discovery failed"
  lb_count="$(jq -er 'if type == "array" then length else error("native ALB response is not an array") end' <<<"$lb_json")" || die "native ALB response schema is invalid"
  [[ "$lb_count" == "1" ]] || die "native ALB discovery did not return exactly one Ingress ALB"
  lb_arn="$(jq -er '.[0].LoadBalancerArn | select(type == "string" and test("^arn:aws:elasticloadbalancing:"))' <<<"$lb_json")" || die "native ALB ARN is invalid"
  tag_json="$(aws "${aws_args[@]}" elbv2 describe-tags --resource-arns "$lb_arn" --output json 2>>"$LOG_FILE")" || die "native ALB tag lookup failed"
  jq -e --arg cluster "$CLUSTER_NAME" --arg stack "kdt-travelplanner-dev-eks" '
    ([.TagDescriptions[]?.Tags[]? | {key:.Key,value:.Value}] as $tags
      | ($tags | any(.key == "elbv2.k8s.aws/cluster" and .value == $cluster))
      and ($tags | any(.key == "ingress.k8s.aws/stack" and .value == $stack)))
  ' <<<"$tag_json" >/dev/null || die "native ALB ownership tags are missing"
  target_groups="$(aws "${aws_args[@]}" elbv2 describe-target-groups --load-balancer-arn "$lb_arn" --query 'TargetGroups[].TargetGroupArn' --output text 2>>"$LOG_FILE")" || die "native target group lookup failed"
  [[ -n "$target_groups" && "$target_groups" != None ]] || die "native ALB has no target groups"
  all_healthy=false
  deadline=$((SECONDS + 180))
  while ((SECONDS < deadline)); do
    all_healthy=true
    for tg in $target_groups; do
      target_health="$(aws "${aws_args[@]}" elbv2 describe-target-health --target-group-arn "$tg" --output json 2>>"$LOG_FILE")" || die "native target health lookup failed"
      if ! jq -e '([.TargetHealthDescriptions[]?.TargetHealth.State] | length > 0 and all(. == "healthy"))' <<<"$target_health" >/dev/null; then
        all_healthy=false
      fi
    done
    [[ "$all_healthy" == true ]] && break
    sleep 5
  done
  [[ "$all_healthy" == true ]] || die "native ALB targets did not become healthy"
  rds_status="$(aws "${aws_args[@]}" rds describe-db-instances --db-instance-identifier "$DATABASE_IDENTIFIER" --query 'DBInstances[0].DBInstanceStatus' --output text 2>>"$LOG_FILE")" || die "native RDS lookup failed"
  [[ "$rds_status" == "available" ]] || die "native RDS is not available"
  redis_status="$(aws "${aws_args[@]}" elasticache describe-replication-groups --replication-group-id "$REDIS_REPLICATION_GROUP_ID" --query 'ReplicationGroups[0].Status' --output text 2>>"$LOG_FILE")" || die "native Redis lookup failed"
  [[ "$redis_status" == "available" ]] || die "native Redis is not available"
  profile_bucket="$PROFILE_IMAGE_BUCKET"
  aws "${aws_args[@]}" s3api head-bucket --bucket "$profile_bucket" >/dev/null 2>>"$LOG_FILE" || die "native profile-image bucket lookup failed"
  jq -n --arg cname "$INGRESS_CNAME_TARGET" --arg alb "$lb_arn" --arg rds "$rds_status" --arg redis "$redis_status" --arg bucket "$profile_bucket" '{schema_version:"dev-eks-operator-smoke/v1",status:"success",cloudflare_cname_target:$cname,alb_arn:$alb,rds_status:$rds,redis_status:$redis,profile_image_bucket:$bucket,target_health:"healthy"}' >"$REPORT_ROOT/operator-native-smoke.redacted.json" || die "native smoke evidence write failed"
  chmod 0600 "$REPORT_ROOT/operator-native-smoke.redacted.json"
}

finalize_repair_success() {
  [[ "$INGRESS_CNAME_TARGET" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]] || die "final CNAME target is invalid"
  consume_authorization_receipt 0 || die "repair authorization receipt could not be terminally consumed"
  jq --arg cname "$INGRESS_CNAME_TARGET" '.status="success" | .cloudflare_cname_target=$cname | .final_checks="passed"' "$REPORT_FILE" >"$REPORT_FILE.tmp"
  mv "$REPORT_FILE.tmp" "$REPORT_FILE"
  if [[ "$DEFER_CNAME_OUTPUT" == true ]]; then
    printf 'CLOUDFLARE_CNAME_TARGET=%s\n' "$INGRESS_CNAME_TARGET" >"$REPORT_ROOT/final-cname.private.txt"
    chmod 0600 "$REPORT_ROOT/final-cname.private.txt"
  else
    printf 'CLOUDFLARE_CNAME_TARGET=%s\n' "$INGRESS_CNAME_TARGET"
  fi
}

prepare_remote() {
  load_runtime_outputs
  write_values
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    capture_dev_eks_state_identity "$REPORT_ROOT/dev-eks-state-before.private.json"
    capture_protected_state_fingerprints "$REPORT_ROOT/protected-states-before.private.json"
  fi
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" ]]; then
    bind_create_receipt_runtime
    validate_create_receipt prepared
  elif [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    bind_repair_receipt_runtime
    validate_repair_receipt
  else
    validate_authorization_receipt
  fi
  upload_action_values
  local render_sha approved_render="$KUBERNETES_RENDER_SHA256"
  MUTATION_STARTED=true
  run_remote_stage prepare >/dev/null
  render_sha=""
  if [[ -s "$REPORT_ROOT/prepare-stdout.txt" ]]; then
    render_sha="$(jq -r '.render_sha256 // empty' <"$REPORT_ROOT/prepare-stdout.txt" 2>/dev/null || true)"
  fi
  if [[ -z "$render_sha" ]]; then
    render_sha="$(grep -Eo 'render_sha256=[0-9a-f]{64}' "$REPORT_ROOT/prepare-stderr.txt" | cut -d= -f2 | tail -1 || true)"
  fi
  [[ "$render_sha" =~ ^[0-9a-f]{64}$ ]] || die "remote prepare did not return a render hash"
  if [[ -n "$approved_render" && "$render_sha" != "$approved_render" ]]; then
    die "remote prepare render hash does not match the explicit Kubernetes approval"
  fi
  KUBERNETES_RENDER_SHA256="$render_sha"
  if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" ]]; then
    bind_create_receipt_render
  elif [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
    bind_repair_receipt_render
  elif [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-autonomous-authorization/v1" ]]; then
    bind_autonomous_receipt_render
  fi
  validate_authorization_receipt "$render_sha"
  printf 'render_sha256=%s\n' "$render_sha" >&2
  jq -n --arg run "$RUN_ID" --arg remote "$REMOTE_RUN_ID" --arg resume "$RESUME_FROM" --arg cluster "$CLUSTER_NAME" --arg bundle "$BUNDLE_REVISION" --arg render "$render_sha" '{schema_version:"dev-eks-deployment-summary/v1",run_id:$run,local_run_id:$run,remote_run_id:$remote,resume_from:(if $resume == "" then null else $resume end),cluster_name:$cluster,bundle_revision_sha256:$bundle,render_sha256:$render,status:"prepared"}' >"$REPORT_FILE"
}

run_kubernetes_stages() {
  [[ -n "$KUBERNETES_RENDER_SHA256" ]] || die "kubernetes render hash is required before mutation"
  validate_authorization_receipt "$KUBERNETES_RENDER_SHA256"
  confirm_exact "APPLY KUBERNETES $KUBERNETES_RENDER_SHA256"
  local stage run_stage=false
  for stage in namespace-secret platform workload ingress-wait; do
    if [[ "$MODE" != "resume" || "$RESUME_FROM" == "prepare" || "$stage" == "$RESUME_FROM" ]]; then
      run_stage=true
    fi
    [[ "$run_stage" == true ]] || continue
    LAST_STAGE="$stage"
    MUTATION_STARTED=true
    run_remote_stage "$stage" "$KUBERNETES_RENDER_SHA256" >/dev/null
    if [[ "$stage" == "ingress-wait" ]]; then
      local cname candidate_count
      local elb_hostname_pattern='([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com'
      candidate_count="$(grep -Ec "^CLOUDFLARE_CNAME_TARGET=${elb_hostname_pattern}$" "$REPORT_ROOT/ingress-wait-stdout.txt" || true)"
      [[ "$candidate_count" -eq 1 ]] || die "ingress-wait did not return exactly one validated CNAME target"
      cname="$(grep -E "^CLOUDFLARE_CNAME_TARGET=${elb_hostname_pattern}$" "$REPORT_ROOT/ingress-wait-stdout.txt")"
      local target="${cname#*=}"
      [[ "$(printf '%s' "$target" | wc -c | tr -d ' ')" -le 253 ]] || die "ingress CNAME target is too long"
      INGRESS_CNAME_TARGET="$target"
      jq --arg cname "$target" '.status="success" | .cloudflare_cname_target=$cname' "$REPORT_FILE" >"$REPORT_FILE.tmp"
      mv "$REPORT_FILE.tmp" "$REPORT_FILE"
      if [[ "$CREATE_RECEIPT_SCHEMA" != "dev-eks-repair-authorization/v1" ]]; then
        printf '%s\n' "$cname"
      fi
    fi
  done
}

main() {
  if [[ "$MODE" == "dry-run" ]]; then
    [[ -z "$TERRAFORM_PLAN" ]] || validate_saved_plan
    jq -n --arg run "$RUN_ID" '{schema_version:"dev-eks-deployment-summary/v1",run_id:$run,status:"dry-run",live_actions:"not-run",provenance_check:"structural-only"}' >"$REPORT_FILE"
    printf 'status=dry-run run_id=%s\n' "$RUN_ID" >&2
    return 0
  fi

  EXECUTION_STARTED=true

  if [[ -n "$AUTHORIZATION_RECEIPT" && "$CREATE_RECEIPT_SCHEMA" != "dev-eks-create-authorization/v1" && "$CREATE_RECEIPT_SCHEMA" != "dev-eks-repair-authorization/v1" ]]; then
    validate_authorization_receipt
  fi

  if [[ "$MODE" == "run" ]]; then
    LAST_STAGE="preflight"
    if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-create-authorization/v1" ]]; then
      validate_create_receipt pre-apply
    fi
    if [[ "$SKIP_TERRAFORM_APPLY" == false ]]; then
      validate_saved_plan
    fi
    verify_live_preflight
    terraform_apply_if_needed
    LAST_STAGE="prepare"
    prepare_remote
    LAST_STAGE="kubernetes"
    run_kubernetes_stages
    LAST_STAGE="smoke"
    MUTATION_STARTED=true
    if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
      run_repair_remote_smoke
      run_operator_native_smoke
      capture_protected_state_fingerprints
      capture_dev_eks_state_identity "$REPORT_ROOT/dev-eks-state-after.private.json"
      compare_protected_state_fingerprints
      compare_dev_eks_state_identity
      finalize_repair_success
    else
      run_remote_smoke
      capture_protected_state_fingerprints
      compare_protected_state_fingerprints
    fi
  elif [[ "$MODE" == "prepare" ]]; then
    LAST_STAGE="preflight"
    verify_live_preflight
    LAST_STAGE="prepare"
    prepare_remote
  elif [[ "$MODE" == "resume" ]]; then
    LAST_STAGE="preflight"
    verify_live_preflight
    if [[ "$RESUME_FROM" == "prepare" ]]; then
      LAST_STAGE="prepare"
      prepare_remote
      [[ "$PREPARE_ONLY" == true ]] && return 0
    else
      load_runtime_outputs
      write_values
      if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
        capture_dev_eks_state_identity "$REPORT_ROOT/dev-eks-state-before.private.json"
        capture_protected_state_fingerprints "$REPORT_ROOT/protected-states-before.private.json"
        bind_repair_receipt_runtime
        validate_repair_receipt "$KUBERNETES_RENDER_SHA256"
      fi
      upload_action_values
      [[ -n "$KUBERNETES_RENDER_SHA256" ]] || die "resume requires a render hash unless it starts at prepare"
      jq -n --arg run "$RUN_ID" --arg remote "$REMOTE_RUN_ID" --arg resume "$RESUME_FROM" --arg cluster "$CLUSTER_NAME" --arg bundle "$BUNDLE_REVISION" --arg render "$KUBERNETES_RENDER_SHA256" '{schema_version:"dev-eks-deployment-summary/v1",run_id:$run,local_run_id:$run,remote_run_id:$remote,resume_from:(if $resume == "" then null else $resume end),cluster_name:$cluster,bundle_revision_sha256:$bundle,render_sha256:$render,status:"resuming"}' >"$REPORT_FILE"
    fi
    LAST_STAGE="kubernetes"
    run_kubernetes_stages
    if [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-repair-authorization/v1" ]]; then
      LAST_STAGE="smoke"
      MUTATION_STARTED=true
      run_repair_remote_smoke
      run_operator_native_smoke
      capture_protected_state_fingerprints
      capture_dev_eks_state_identity "$REPORT_ROOT/dev-eks-state-after.private.json"
      compare_protected_state_fingerprints
      compare_dev_eks_state_identity
      finalize_repair_success
    fi
  fi
}

main "$@"
