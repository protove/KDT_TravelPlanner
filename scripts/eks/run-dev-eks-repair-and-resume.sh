#!/usr/bin/env bash
set -euo pipefail

# SCRUM-53 retained-environment recovery coordinator. It has no Terraform,
# cleanup, IAM or Cloudflare action surface. v13 completion leases preserve the
# same explicitly approved scope across recoverable failures.
umask 077

MODE="issue"
AWS_PROFILE="kdt-travel-terraform"
REGION="ap-northeast-2"
EXPECTED_ACCOUNT_ID=""
CLUSTER_NAME="kdt-travelplanner-dev-eks"
CAPSULE_PATH=""
PREFLIGHT_PATH=""
RECEIPT_PATH=""
APPROVAL=""
PRIOR_APPROVAL_RECEIPT=""
PRIOR_APPROVAL_SCOPE=""
RUN_ID=""
SSM_TIMEOUT_SECONDS="1800"
OFFLINE_TEST="${OFFLINE_TEST:-false}"

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HANDOFF_PATH="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v11.yaml"
CAPSULE_DEFAULT="$SCRIPT_ROOT/evidence/eks-deploy/20260824T133440Z-15798/action-values.json"
REPAIR_HELPER="$SCRIPT_ROOT/scripts/eks/repair-dev-eks-bastion.sh"
SMOKE_HELPER="$SCRIPT_ROOT/scripts/eks/run-dev-eks-repair-smoke.sh"
DEPLOYER="$SCRIPT_ROOT/scripts/eks/deploy-dev-eks.sh"
REPAIR_DEPLOYMENT_RUNNER="$SCRIPT_ROOT/scripts/eks/run-dev-eks-deployment.sh"
EXPECTED_HANDOFF_SHA256="b0441f0a4af42a807463a4d102c74e7606f36b16785f5544be365d05a626be19"
EXPECTED_MANIFEST_SHA256="231da893f466968f34fadc7cd9c33eac26f72509f196da18cf93f2eac8c3d290"
EXPECTED_BACKEND_SHA256="86af5e85a52d52f36f4f64274d238e68985e5084f1554eab9b6364e9f2907515"
EXPECTED_CAPSULE_SHA256="3c0a636a230247a10c785822487df1ca8b5a1cfeead4d695f54afdc98d4f44f8"
RETAINED_LIVE_PREFLIGHT="$SCRIPT_ROOT/evidence/eks-deploy/20260825T054716Z-45689/live-preflight.private.json"
OPERATOR_POLICY_EVIDENCE="$SCRIPT_ROOT/evidence/eks-deploy/20260825T054716Z-45689/iam-effective-policy.private.json"
PREFLIGHT_TMP_ROOT=""
RUN_EXECUTION_STARTED=false

usage() {
  cat >&2 <<'USAGE'
Usage: run-dev-eks-repair-and-resume.sh --mode issue|run|completion-issue|completion-run
  --mode preflight creates a fresh mode-0600 read-only live preflight
  --action-values-capsule <mode-0600 JSON>
  --preflight-json <mode-0600 N30 read-only preflight JSON>
  --authorization-receipt <mode-0600 pending/active v11 receipt>
  --prior-authorization-receipt <mode-0600 consumed receipt proving the prior explicit approval>
  --prior-approval-scope-sha256 <64 lowercase hex prior approval scope>
  [--approval "APPLY DEV-EKS REPAIR-AND-RESUME <scope-sha256>"]
  [--run-id <YYYYMMDDTHHMMSSZ-number>] [--expected-account-id <12 digits>]
USAGE
}

die() { printf 'status=failed reason=%s\n' "$1" >&2; exit 1; }

consume_active_receipt() {
  local exit_status="${1:-0}" terminal_result="failed" consumed
  if [[ "$exit_status" -eq 0 ]]; then terminal_result="completed"; fi
  [[ -n "$RECEIPT_PATH" && -f "$RECEIPT_PATH" && ! -L "$RECEIPT_PATH" ]] || return 0
  jq -e '.schema_version == "dev-eks-repair-authorization/v1" and .status == "active"' "$RECEIPT_PATH" >/dev/null 2>&1 || return 0
  if [[ "$exit_status" -ne 0 ]] && jq -e '.completion_lease == true and .continuity_verified == true' "$RECEIPT_PATH" >/dev/null 2>&1; then
    return 0
  fi
  consumed="$(mktemp "${RECEIPT_PATH}.consumed.XXXXXX")" || return 1
  jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg result "$terminal_result" \
    '.status="consumed" | .consumed_at=$now | .terminal_result=$result' \
    "$RECEIPT_PATH" >"$consumed" || { rm -f -- "$consumed"; return 1; }
  chmod 0600 "$consumed" || { rm -f -- "$consumed"; return 1; }
  mv -f -- "$consumed" "$RECEIPT_PATH" || { rm -f -- "$consumed"; return 1; }
}

cleanup() {
  local exit_status=$?
  if [[ "$RUN_EXECUTION_STARTED" == true ]] && ! consume_active_receipt "$exit_status"; then
    exit_status=1
    printf 'status=failed reason=repair authorization receipt could not be terminally invalidated\n' >&2
  fi
  if [[ -n "${PREFLIGHT_TMP_ROOT:-}" && -d "$PREFLIGHT_TMP_ROOT" && ! -L "$PREFLIGHT_TMP_ROOT" ]]; then
    rm -rf -- "$PREFLIGHT_TMP_ROOT"
  fi
  trap - EXIT
  exit "$exit_status"
}
trap cleanup EXIT

while (($#)); do
  case "$1" in
    --mode) MODE="${2:?missing value for --mode}"; shift 2 ;;
    --aws-profile) AWS_PROFILE="${2:?missing value for --aws-profile}"; shift 2 ;;
    --region) REGION="${2:?missing value for --region}"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="${2:?missing value for --cluster-name}"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="${2:?missing value for --expected-account-id}"; shift 2 ;;
    --action-values-capsule) CAPSULE_PATH="${2:?missing value for --action-values-capsule}"; shift 2 ;;
    --preflight-json) PREFLIGHT_PATH="${2:?missing value for --preflight-json}"; shift 2 ;;
    --authorization-receipt) RECEIPT_PATH="${2:?missing value for --authorization-receipt}"; shift 2 ;;
    --prior-authorization-receipt) PRIOR_APPROVAL_RECEIPT="${2:?missing value for --prior-authorization-receipt}"; shift 2 ;;
    --prior-approval-scope-sha256) PRIOR_APPROVAL_SCOPE="${2:?missing value for --prior-approval-scope-sha256}"; shift 2 ;;
    --approval) APPROVAL="${2:?missing value for --approval}"; shift 2 ;;
    --run-id) RUN_ID="${2:?missing value for --run-id}"; shift 2 ;;
    --ssm-timeout-seconds) SSM_TIMEOUT_SECONDS="${2:?missing value for --ssm-timeout-seconds}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument" ;;
  esac
done

[[ "$MODE" =~ ^(preflight|issue|run|completion-issue|completion-run)$ ]] || die "mode must be preflight, issue, run, completion-issue or completion-run"
[[ "$REGION" == "ap-northeast-2" ]] || die "region must be ap-northeast-2"
[[ "$CLUSTER_NAME" =~ ^[a-z0-9][a-z0-9-]{0,99}$ ]] || die "cluster name is invalid"
[[ "$SSM_TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$SSM_TIMEOUT_SECONDS" -le 7200 ]] || die "SSM timeout is invalid"
CAPSULE_PATH="${CAPSULE_PATH:-$CAPSULE_DEFAULT}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
[[ "$RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || die "run id has an invalid shape"
COORDINATOR_EVIDENCE_ROOT="$SCRIPT_ROOT/evidence/eks-deploy/$RUN_ID"

for command_name in jq sha256sum ruby mktemp; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
done
if [[ "$MODE" == "preflight" || "$MODE" == "run" || "$MODE" == "completion-issue" || "$MODE" == "completion-run" ]]; then
  for command_name in aws bash; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
  done
fi

validate_handoff() {
  local actual details
  [[ -f "$HANDOFF_PATH" && ! -L "$HANDOFF_PATH" ]] || die "v11 handoff is missing"
  actual="$(sha256sum "$HANDOFF_PATH" | awk '{print $1}')"
  [[ "$actual" == "$EXPECTED_HANDOFF_SHA256" ]] || die "v11 handoff SHA-256 does not match"
  details="$(ruby -ryaml -rdigest -rjson -e '
    h = YAML.safe_load(File.binread(ARGV.fetch(0)), aliases: false)
    bytes = File.binread(h.fetch("manifest_path"))
    m = YAML.safe_load(bytes, aliases: false)
    puts JSON.generate({handoff:h,manifest_sha:Digest::SHA256.hexdigest(bytes),manifest:m})
  ' "$HANDOFF_PATH")" || die "v11 handoff could not be parsed"
  jq -e --arg expected "$EXPECTED_MANIFEST_SHA256" '
    .handoff.schema_version == "plan-handoff/v1" and .handoff.manifest_schema_version == "plan-manifest/v3" and
    .handoff.plan_id == "dev-eks-deployment-automation" and .handoff.version == 11 and .handoff.status == "ready" and
    .handoff.immutable == true and .handoff.manifest_sha256 == $expected and .manifest_sha == $expected and
    .manifest.schema_version == "plan-manifest/v3" and .manifest.plan_id == "dev-eks-deployment-automation" and
    .manifest.version == 11 and .manifest.status == "ready" and .manifest.plan_artifact.immutable == true
  ' <<<"$details" >/dev/null || die "v11 handoff or manifest identity is invalid"
}

validate_capsule() {
  [[ -f "$CAPSULE_PATH" && ! -L "$CAPSULE_PATH" ]] || die "action-values capsule is missing"
  [[ "$(stat -f '%Lp' "$CAPSULE_PATH" 2>/dev/null || stat -c '%a' "$CAPSULE_PATH" 2>/dev/null)" == "600" ]] || die "action-values capsule must be mode 0600"
  CAPSULE_PATH="$(cd "$(dirname "$CAPSULE_PATH")" && pwd)/$(basename "$CAPSULE_PATH")"
  [[ "$(sha256sum "$CAPSULE_PATH" | awk '{print $1}')" == "$EXPECTED_CAPSULE_SHA256" ]] || die "canonical action-values capsule SHA-256 does not match"
  jq -e 'type == "object" and (.backend_image | type == "string" and test("^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")) and (.backend_hostname | type == "string") and (.frontend_origin | type == "string") and (has("SecretString") | not) and (has("SecretBinary") | not)' "$CAPSULE_PATH" >/dev/null || die "action-values capsule schema or redaction check failed"
  if [[ -z "$EXPECTED_ACCOUNT_ID" ]]; then
    EXPECTED_ACCOUNT_ID="$(jq -er '.backend_image | capture("^(?<account>[0-9]{12})\\.").account' "$CAPSULE_PATH")" || die "account cannot be derived from capsule"
  fi
  [[ "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || die "expected account id is invalid"
}

validate_private_path() {
  local path="$1" label="$2" required_root="${3:-}" parent current component canonical_parent canonical_root
  [[ "$path" == /* ]] || die "$label path must be absolute"
  [[ "$path" != *$'\n'* && "$path" != *$'\r'* ]] || die "$label path contains a control character"
  [[ "$path" != *'//' && "$path" != *'/./'* && "$path" != */'.' && "$path" != *'/../'* && "$path" != */'..' ]] || die "$label path contains an unsafe component"
  while IFS= read -r component; do
    case "$component" in
      ''|.) die "$label path contains an unsafe component" ;;
      ..) die "$label path contains an unsafe component" ;;
    esac
  done < <(printf '%s\n' "${path#/}" | tr '/' '\n')
  parent="$(dirname -- "$path")"
  current="/"
  while IFS= read -r component; do
    [[ -n "$component" ]] || continue
    current="${current%/}/$component"
    if [[ -L "$current" ]]; then
      case "$current" in
        /var|/tmp|/var/folders/[[:alnum:]][[:alnum:]]) ;;
        *) die "$label path must not contain a symlink" ;;
      esac
    fi
  done < <(printf '%s\n' "${parent#/}" | tr '/' '\n')
  if [[ -n "$required_root" && "$OFFLINE_TEST" != true ]]; then
    [[ "$required_root" == /* ]] || die "internal required path root is not absolute"
    canonical_root="$(cd -P -- "$required_root" 2>/dev/null && pwd -P)" || die "$label required path root is unavailable"
    if [[ -d "$parent" ]]; then
      canonical_parent="$(cd -P -- "$parent" 2>/dev/null && pwd -P)" || die "$label parent path could not be canonicalized"
      [[ "$canonical_parent" == "$canonical_root" || "$canonical_parent" == "$canonical_root"/* ]] || die "$label path must remain under the current run evidence directory"
    else
      [[ "$path" == "$canonical_root"/* || "$path" == "$required_root"/* ]] || die "$label path must remain under the current run evidence directory"
    fi
  fi
}

validate_receipt_parent_path() {
  validate_private_path "$1" "receipt parent" "$COORDINATOR_EVIDENCE_ROOT"
}

validate_preflight_path() {
  validate_private_path "$1" "preflight"
}

state_has_required_policy_evidence() {
  local state_file="$1"
  jq -e --arg bastion_role "kdt-travelplanner-dev-eks-bastion" --arg controller_role "kdt-travelplanner-dev-aws-load-balancer-controller" --argjson bastion_required '["eks:DescribeCluster","s3:ListBucket","s3:GetObject","ssm:GetParameter","secretsmanager:GetSecretValue"]' --argjson controller_required '["elasticloadbalancing:DescribeLoadBalancers","elasticloadbalancing:DescribeTags","elasticloadbalancing:DescribeTargetGroups","elasticloadbalancing:DescribeTargetHealth","elasticloadbalancing:CreateLoadBalancer","elasticloadbalancing:CreateTargetGroup","ec2:DescribeSubnets","ec2:DescribeSecurityGroups","acm:DescribeCertificate"]' '
    def actions($policy):
      try ($policy | fromjson | .Statement[]? | select(.Effect == "Allow") | .Action | if type == "array" then .[] else . end) catch empty;
    def role_exists($name): any(.resources[]?; .type == "aws_iam_role" and any(.instances[]?.attributes?; .name == $name));
    def inline_policy_has($resource_name; $role; $required):
      any(.resources[]?; .type == "aws_iam_role_policy" and .name == $resource_name and any(.instances[]?.attributes?; .role == $role and ([actions(.policy)] | unique) as $allowed | all($required[]; . as $wanted | ($allowed | index($wanted)) != null)));
    (role_exists($bastion_role) and inline_policy_has("bastion_runtime"; $bastion_role; $bastion_required) and
      any(.resources[]?; .type == "aws_iam_role_policy_attachment" and .name == "bastion_ssm" and any(.instances[]?.attributes?; .role == $bastion_role and .policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"))) and
    (role_exists($controller_role) and inline_policy_has("load_balancer_controller"; $controller_role; $controller_required))
  ' "$state_file" >/dev/null
}

operator_policy_evidence_verified() {
  [[ -f "$OPERATOR_POLICY_EVIDENCE" && ! -L "$OPERATOR_POLICY_EVIDENCE" ]] || return 1
  jq -e '
    type == "object" and (.Statement | type == "array") and
    any(.Statement[]?; .Effect == "Allow" and .Action == "ssm:SendCommand" and ((.Resource | type) == "string") and ((.Resource | contains(":instance/*")) or (.Resource | contains(":document/AWS-RunShellScript")))) and
    any(.Statement[]?; .Effect == "Allow" and .Action == "ssm:GetCommandInvocation" and .Resource == "*" and .Condition.StringEquals["aws:RequestedRegion"] == "ap-northeast-2")
  ' "$OPERATOR_POLICY_EVIDENCE" >/dev/null
}

validate_preflight() {
  validate_private_path "$PREFLIGHT_PATH" "preflight" "$COORDINATOR_EVIDENCE_ROOT"
  [[ -f "$PREFLIGHT_PATH" && ! -L "$PREFLIGHT_PATH" ]] || die "read-only preflight JSON is missing"
  [[ "$(stat -f '%Lp' "$PREFLIGHT_PATH" 2>/dev/null || stat -c '%a' "$PREFLIGHT_PATH" 2>/dev/null)" == "600" ]] || die "preflight JSON must be mode 0600"
  jq -e --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg backend "$EXPECTED_BACKEND_SHA256" '
    type == "object" and .schema_version == "dev-eks-v11-live-preflight/v1" and
    .expected_account_id == $account and .expected_region == $region and .backend_config_sha256 == $backend and
    (.bastion_instance_id | type == "string" and test("^i-[0-9a-f]+$")) and (.cluster_name | type == "string" and length > 0) and
    (.kubernetes_version == "1.35") and (.kubernetes_version_status == "STANDARD_SUPPORT") and
    (.monitoring_bucket | type == "string" and length > 0) and (.monitoring_prefix | type == "string" and length > 0) and
    (.retained_v9_run_id | type == "string") and (.retained_v9_plan_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.bundle_revision_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and (.kubectl_version == "1.35.6") and
    (.dev_eks_state_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.dev_eks_state_lineage | type == "string" and length > 0) and
    (.dev_eks_state_serial | type == "number" and . >= 0 and . == floor) and
    (.bastion_tags | type == "object" and .Environment == "dev" and .Stack == "dev-eks" and .Phase == "eks-baseline" and .Project == "kdt-travelplanner" and .Name == "kdt-travelplanner-dev-eks-bastion") and
    (.state_fingerprints | type == "array" and length == 4 and (map(.key) | sort) == ["dev-eks/terraform.tfstate","dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"] and all(.[]; (.sha256 | type == "string" and test("^[0-9a-f]{64}$")) and (.lineage | type == "string" and length > 0) and (.serial | type == "number" and . >= 0 and . == floor))) and
    (.helper_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.smoke_helper_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.operator_iam_status == "operator-policy-evidence-verified") and
    (.bastion_iam_status == "state-policy-evidence-verified") and
    (.controller_iam_status == "state-policy-evidence-verified")
  ' "$PREFLIGHT_PATH" >/dev/null || die "read-only v11 preflight is incomplete or principal capability status is missing"
  [[ "$(sha256sum "$REPAIR_HELPER" | awk '{print $1}')" == "$(jq -r '.helper_sha256' "$PREFLIGHT_PATH")" ]] || die "Bastion repair helper checksum is not the fresh preflight checksum"
  [[ "$(sha256sum "$SMOKE_HELPER" | awk '{print $1}')" == "$(jq -r '.smoke_helper_sha256' "$PREFLIGHT_PATH")" ]] || die "repair smoke helper checksum is not the fresh preflight checksum"
}

capture_live_preflight() {
  local account instance_json cluster_json support_json support_status cluster_version cluster_arn
  local instance_count bastion bastion_tags bucket prefix bundle_tmp bundle_revision state_bucket state_tmp
  local state_entries='[]' key state_hash state_lineage state_serial dev_eks_state_tmp prior_run prior_plan prior_plan_path
  local backend_image backend_repo backend_digest ecr_json bastion_iam_status="state-policy-evidence-unverified" controller_iam_status="state-policy-evidence-unverified"
  local ssm_info role_name err operator_iam_status="operator-policy-evidence-unverified"
  PREFLIGHT_PATH="${PREFLIGHT_PATH:-$COORDINATOR_EVIDENCE_ROOT/live-preflight.private.json}"
  mkdir -p "$COORDINATOR_EVIDENCE_ROOT"
  chmod 0700 "$COORDINATOR_EVIDENCE_ROOT"
  validate_private_path "$PREFLIGHT_PATH" "preflight output" "$COORDINATOR_EVIDENCE_ROOT"
  [[ ! -e "$PREFLIGHT_PATH" && ! -L "$PREFLIGHT_PATH" ]] || die "refusing to overwrite an existing or symlinked preflight"
  PREFLIGHT_TMP_ROOT="$(mktemp -d "$COORDINATOR_EVIDENCE_ROOT/preflight.XXXXXX")" || die "preflight temporary directory could not be created"
  chmod 0700 "$PREFLIGHT_TMP_ROOT"
  err="$PREFLIGHT_TMP_ROOT/aws.stderr"

  account="$(aws --profile "$AWS_PROFILE" --region "$REGION" sts get-caller-identity --query Account --output text 2>"$err")" || die "preflight STS identity query failed"
  [[ "$account" == "$EXPECTED_ACCOUNT_ID" ]] || die "preflight account does not match the expected account"
  instance_json="$(aws --profile "$AWS_PROFILE" --region "$REGION" ec2 describe-instances --filters \
    Name=instance-state-name,Values=running \
    Name=tag:Environment,Values=dev Name=tag:Stack,Values=dev-eks \
    Name=tag:Phase,Values=eks-baseline Name=tag:Project,Values=kdt-travelplanner \
    Name=tag:Name,Values=kdt-travelplanner-dev-eks-bastion --output json 2>"$err")" || die "preflight Bastion discovery failed"
  instance_count="$(jq -er '[.Reservations[]?.Instances[]?] | length' <<<"$instance_json")" || die "preflight Bastion response schema is invalid"
  [[ "$instance_count" == "1" ]] || die "preflight did not find exactly one running canonical Bastion"
  bastion="$(jq -er '[.Reservations[]?.Instances[]?][0].InstanceId' <<<"$instance_json")"
  bastion_tags="$(jq -cer '[.Reservations[]?.Instances[]?][0].Tags // [] | map({key:.Key,value:.Value}) | from_entries' <<<"$instance_json")" || die "preflight Bastion tags are invalid"
  jq -e '.Environment == "dev" and .Stack == "dev-eks" and .Phase == "eks-baseline" and .Project == "kdt-travelplanner" and .Name == "kdt-travelplanner-dev-eks-bastion"' <<<"$bastion_tags" >/dev/null || die "preflight Bastion ownership tags are not exact"

  cluster_json="$(aws --profile "$AWS_PROFILE" --region "$REGION" eks describe-cluster --name "$CLUSTER_NAME" --output json 2>"$err")" || die "preflight EKS identity query failed"
  cluster_arn="$(jq -er '.cluster.arn' <<<"$cluster_json")" || die "preflight EKS ARN is missing"
  cluster_version="$(jq -er '.cluster.version' <<<"$cluster_json")" || die "preflight EKS version is missing"
  [[ "$cluster_arn" == "arn:aws:eks:${REGION}:${EXPECTED_ACCOUNT_ID}:cluster/${CLUSTER_NAME}" ]] || die "preflight EKS ARN is not exact"
  [[ "$(jq -er '.cluster.status' <<<"$cluster_json")" == "ACTIVE" && "$cluster_version" == "1.35" ]] || die "preflight EKS is not ACTIVE at Kubernetes 1.35"
  support_json="$(aws --profile "$AWS_PROFILE" --region "$REGION" eks describe-cluster-versions --cluster-type eks --cluster-versions "$cluster_version" --no-paginate --output json 2>"$err")" || die "preflight EKS support query failed"
  jq -e --arg version "$cluster_version" 'type == "object" and (.clusterVersions | type == "array" and length == 1) and .clusterVersions[0].clusterVersion == $version and .clusterVersions[0].clusterType == "eks" and .clusterVersions[0].versionStatus == "STANDARD_SUPPORT"' <<<"$support_json" >/dev/null || die "preflight EKS minor is not STANDARD_SUPPORT"
  support_status="STANDARD_SUPPORT"

  bucket="kdt-travelplanner-dev-eks-monitoring-config-${EXPECTED_ACCOUNT_ID}"
  prefix="kubernetes/monitoring"
  bundle_tmp="$PREFLIGHT_TMP_ROOT/bundle-manifest.json"
  aws --profile "$AWS_PROFILE" --region "$REGION" s3api get-object --bucket "$bucket" --key "$prefix/bundle-manifest.json" "$bundle_tmp" >/dev/null 2>"$err" || die "preflight monitoring bundle query failed"
  bundle_revision="$(jq -er '.revision | select(type == "string" and test("^[0-9a-f]{64}$"))' "$bundle_tmp")" || die "preflight monitoring bundle revision is invalid"

  [[ -f "$RETAINED_LIVE_PREFLIGHT" && ! -L "$RETAINED_LIVE_PREFLIGHT" ]] || die "retained v9 live preflight artifact is missing"
  jq -e --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" '.schema_version == "dev-eks-live-preflight/v1" and .account_id == $account and .region == $region' "$RETAINED_LIVE_PREFLIGHT" >/dev/null || die "retained v9 live preflight lineage is invalid"
  prior_run="$(jq -er '.run_id' "$RETAINED_LIVE_PREFLIGHT")"
  prior_plan="$(jq -er '.plan_sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$RETAINED_LIVE_PREFLIGHT")"
  prior_plan_path="$SCRIPT_ROOT/evidence/eks-deploy/$prior_run/create-plan.sha256"
  [[ -f "$prior_plan_path" && "$(awk 'NF {print $1; exit}' "$prior_plan_path")" == "$prior_plan" ]] || die "retained v9 plan identity is invalid"

  state_bucket="kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}"
  while IFS= read -r key; do
    state_tmp="$PREFLIGHT_TMP_ROOT/$(printf '%s' "$key" | tr '/.' '__')"
    aws --profile "$AWS_PROFILE" --region "$REGION" s3api get-object --bucket "$state_bucket" --key "$key" "$state_tmp" >/dev/null 2>"$err" || die "preflight State read failed for $key"
    state_hash="$(sha256sum "$state_tmp" | awk '{print $1}')"
    state_lineage="$(jq -er '.lineage | select(type == "string" and length > 0)' "$state_tmp")" || die "preflight State lineage is missing for $key"
    state_serial="$(jq -er '.serial | numbers' "$state_tmp")" || die "preflight State serial is missing for $key"
    state_entries="$(jq -c --arg key "$key" --arg sha "$state_hash" --arg lineage "$state_lineage" --argjson serial "$state_serial" '. + [{key:$key,sha256:$sha,lineage:$lineage,serial:$serial}]' <<<"$state_entries")"
    if [[ "$key" == "dev-eks/terraform.tfstate" ]]; then dev_eks_state_tmp="$state_tmp"; fi
  done < <(printf '%s\n' dev/terraform.tfstate dev-runtime/terraform.tfstate dev-load-test/terraform.tfstate dev-eks/terraform.tfstate)
  state_entries="$(jq -c 'sort_by(.key)' <<<"$state_entries")"

  backend_image="$(jq -er '.backend_image' "$CAPSULE_PATH")"
  backend_repo="${backend_image#*.amazonaws.com/}"
  backend_digest="${backend_repo##*@}"
  backend_repo="${backend_repo%@*}"
  ecr_json="$(aws --profile "$AWS_PROFILE" --region "$REGION" ecr describe-images --repository-name "$backend_repo" --image-ids imageDigest="$backend_digest" --output json 2>"$err")" || die "preflight backend image provenance query failed"
  jq -e --arg digest "$backend_digest" '(.imageDetails | type == "array" and length == 1 and .[0].imageDigest == $digest)' <<<"$ecr_json" >/dev/null || die "preflight backend image digest is not exact"

  if operator_policy_evidence_verified; then operator_iam_status="operator-policy-evidence-verified"; fi
  if state_has_required_policy_evidence "$dev_eks_state_tmp"; then
    bastion_iam_status="state-policy-evidence-verified"
    controller_iam_status="state-policy-evidence-verified"
  fi
  if ssm_info="$(aws --profile "$AWS_PROFILE" --region "$REGION" ssm describe-instance-information --filters "Key=InstanceIds,Values=$bastion" --output json 2>"$err")"; then
    if jq -e --arg id "$bastion" 'any(.InstanceInformationList[]?; .InstanceId == $id and .PingStatus == "Online")' <<<"$ssm_info" >/dev/null; then
      : # Online status is supplemental; the authorization gate remains deployed-policy evidence.
    fi
  fi
  role_name="${CLUSTER_NAME}-aws-load-balancer-controller"
  if [[ -n "$dev_eks_state_tmp" ]] && jq -e 'any(.resources[]?; .type == "aws_iam_role" and .name == "load_balancer_controller")' "$dev_eks_state_tmp" >/dev/null 2>&1; then :; fi
  if aws --profile "$AWS_PROFILE" --region "$REGION" iam get-role --role-name "$role_name" --output json >/dev/null 2>"$err"; then :; fi

  jq -n --arg schema "dev-eks-v11-live-preflight/v1" --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg account "$account" --arg region "$REGION" --arg backend "$EXPECTED_BACKEND_SHA256" --arg bastion "$bastion" --arg cluster "$CLUSTER_NAME" --arg bucket "$bucket" --arg prefix "$prefix" --arg prior_run "$prior_run" --arg prior_plan "$prior_plan" --arg bundle "$bundle_revision" --argjson tags "$bastion_tags" --argjson states "$state_entries" --arg operator_status "$operator_iam_status" --arg bastion_status "$bastion_iam_status" --arg controller_status "$controller_iam_status" --arg helper "$(sha256sum "$REPAIR_HELPER" | awk '{print $1}')" --arg smoke_helper "$(sha256sum "$SMOKE_HELPER" | awk '{print $1}')" --arg state_sha "$(jq -er '.[] | select(.key == "dev-eks/terraform.tfstate") | .sha256' <<<"$state_entries")" --arg state_lineage "$(jq -er '.[] | select(.key == "dev-eks/terraform.tfstate") | .lineage' <<<"$state_entries")" --argjson state_serial "$(jq -er '.[] | select(.key == "dev-eks/terraform.tfstate") | .serial' <<<"$state_entries")" --arg version "$cluster_version" --arg support "$support_status" \
    '{schema_version:$schema,captured_at:$captured,expected_account_id:$account,expected_region:$region,backend_config_sha256:$backend,bastion_instance_id:$bastion,bastion_tags:$tags,cluster_name:$cluster,kubernetes_version:$version,kubernetes_version_status:$support,monitoring_bucket:$bucket,monitoring_prefix:$prefix,retained_v9_run_id:$prior_run,retained_v9_plan_sha256:$prior_plan,bundle_revision_sha256:$bundle,kubectl_version:"1.35.6",dev_eks_state_sha256:$state_sha,dev_eks_state_lineage:$state_lineage,dev_eks_state_serial:$state_serial,state_fingerprints:$states,helper_sha256:$helper,smoke_helper_sha256:$smoke_helper,operator_iam_status:$operator_status,bastion_iam_status:$bastion_status,controller_iam_status:$controller_status}' >"$PREFLIGHT_PATH" || die "preflight evidence could not be serialized"
  chmod 0600 "$PREFLIGHT_PATH"
  rm -f -- "$err"
  printf 'status=preflight path=%s\n' "$PREFLIGHT_PATH"
}

write_ssm_failure_evidence() {
  local status="$1" reason="$2" command_id="${3:-}" response_code="${4:-}" path
  path="$COORDINATOR_EVIDENCE_ROOT/ssm-repair-failure.private.json"
  mkdir -p "$COORDINATOR_EVIDENCE_ROOT" || die "SSM failure evidence directory could not be created"
  jq -n --arg status "$status" --arg reason "$reason" --arg command_id "$command_id" --arg response_code "$response_code" \
    '{schema_version:"dev-eks-ssm-failure/v2",stage:"bastion-repair",status:$status,command_id:(if $command_id == "" then null else $command_id end),response_code:(if $response_code == "" then null else ($response_code|tonumber) end),safe_reason:$reason,standard_error_present:true}' \
    >"$path" || die "SSM failure evidence could not be serialized"
  chmod 0600 "$path" || die "SSM failure evidence permissions could not be secured"
}

validate_live_preflight_identity() {
  local account bastion cluster bucket prefix state_bucket prior_run prior_plan expected_plan plan_path
  local err instance_json cluster_json support_json state_tmp bundle_tmp bundle_key state_hash state_lineage state_serial
  local instance_count cluster_arn cluster_status cluster_version bundle_revision support_status state_entries key
  [[ -n "$AWS_PROFILE" ]] || die "run mode requires an AWS profile"
  [[ -n "$PREFLIGHT_PATH" ]] || die "run mode requires the same read-only preflight JSON"
  validate_preflight
  bastion="$(jq -er '.bastion_instance_id' "$PREFLIGHT_PATH")"
  cluster="$(jq -er '.cluster_name' "$PREFLIGHT_PATH")"
  bucket="$(jq -er '.monitoring_bucket' "$PREFLIGHT_PATH")"
  prefix="$(jq -er '.monitoring_prefix' "$PREFLIGHT_PATH")"
  prior_run="$(jq -er '.retained_v9_run_id' "$PREFLIGHT_PATH")"
  prior_plan="$(jq -er '.retained_v9_plan_sha256' "$PREFLIGHT_PATH")"
  state_bucket="kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}"
  mkdir -p "$COORDINATOR_EVIDENCE_ROOT" || die "live preflight evidence directory could not be created"
  err="$(mktemp "$COORDINATOR_EVIDENCE_ROOT/live-preflight-error.XXXXXX")" || die "live preflight error file could not be created"

  if ! account="$(aws --profile "$AWS_PROFILE" --region "$REGION" sts get-caller-identity --query Account --output text 2>"$err")"; then
    rm -f -- "$err"
    die "live preflight STS identity query failed"
  fi
  [[ "$account" == "$EXPECTED_ACCOUNT_ID" ]] || { rm -f -- "$err"; die "live preflight account does not match the exact preflight account"; }

  if ! instance_json="$(aws --profile "$AWS_PROFILE" --region "$REGION" ec2 describe-instances --instance-ids "$bastion" --output json 2>"$err")"; then
    rm -f -- "$err"
    die "live preflight Bastion identity query failed"
  fi
  instance_count="$(jq -er '[.Reservations[]?.Instances[]?] | length' <<<"$instance_json")" || { rm -f -- "$err"; die "live preflight Bastion response schema is invalid"; }
  [[ "$instance_count" == "1" ]] || { rm -f -- "$err"; die "live preflight did not return exactly one Bastion"; }
  jq -e --arg id "$bastion" '
    ([.Reservations[]?.Instances[]?] | .[0].InstanceId == $id and .[0].State.Name == "running") and
    ([.Reservations[]?.Instances[]?] | .[0].Tags // [] | map({key:.Key,value:.Value}) |
      any(.[]; .key == "Environment" and .value == "dev") and
      any(.[]; .key == "Stack" and .value == "dev-eks") and
      any(.[]; .key == "Phase" and .value == "eks-baseline") and
      any(.[]; .key == "Project" and .value == "kdt-travelplanner") and
      any(.[]; .key == "Name" and .value == "kdt-travelplanner-dev-eks-bastion"))
  ' <<<"$instance_json" >/dev/null || { rm -f -- "$err"; die "live preflight Bastion identity or canonical ownership tags differ"; }

  if ! cluster_json="$(aws --profile "$AWS_PROFILE" --region "$REGION" eks describe-cluster --name "$cluster" --output json 2>"$err")"; then
    rm -f -- "$err"
    die "live preflight EKS identity query failed"
  fi
  cluster_arn="$(jq -er '.cluster.arn' <<<"$cluster_json")" || { rm -f -- "$err"; die "live preflight EKS response schema is invalid"; }
  cluster_status="$(jq -er '.cluster.status' <<<"$cluster_json")" || { rm -f -- "$err"; die "live preflight EKS status is missing"; }
  cluster_version="$(jq -er '.cluster.version' <<<"$cluster_json")" || { rm -f -- "$err"; die "live preflight EKS version is missing"; }
  [[ "$cluster_arn" == "arn:aws:eks:${REGION}:${EXPECTED_ACCOUNT_ID}:cluster/${cluster}" && "$cluster_status" == "ACTIVE" && "$cluster_version" == "1.35" ]] || { rm -f -- "$err"; die "live preflight EKS identity, status or minor differs"; }
  if ! support_json="$(aws --profile "$AWS_PROFILE" --region "$REGION" eks describe-cluster-versions --cluster-type eks --cluster-versions "$cluster_version" --no-paginate --output json 2>"$err")"; then
    rm -f -- "$err"
    die "live preflight EKS support metadata query failed"
  fi
  jq -e --arg version "$cluster_version" '
    type == "object" and (.clusterVersions | type == "array" and length == 1) and
    .clusterVersions[0].clusterVersion == $version and .clusterVersions[0].clusterType == "eks" and
    .clusterVersions[0].versionStatus == "STANDARD_SUPPORT"
  ' <<<"$support_json" >/dev/null || { rm -f -- "$err"; die "live preflight EKS minor is not STANDARD_SUPPORT or response shape is invalid"; }
  support_status="STANDARD_SUPPORT"

  bundle_key="$prefix/bundle-manifest.json"
  bundle_tmp="$(mktemp "$COORDINATOR_EVIDENCE_ROOT/bundle-manifest.XXXXXX")" || { rm -f -- "$err"; die "live preflight bundle file could not be created"; }
  if ! aws --profile "$AWS_PROFILE" --region "$REGION" s3api get-object --bucket "$bucket" --key "$bundle_key" "$bundle_tmp" >/dev/null 2>"$err"; then
    rm -f -- "$err" "$bundle_tmp"
    die "live preflight monitoring bundle query failed"
  fi
  bundle_revision="$(jq -er '.revision' "$bundle_tmp")" || { rm -f -- "$err" "$bundle_tmp"; die "live preflight bundle schema is invalid"; }
  [[ "$bundle_revision" == "$(jq -er '.bundle_revision_sha256' "$PREFLIGHT_PATH")" ]] || { rm -f -- "$err" "$bundle_tmp"; die "live preflight bundle revision differs"; }
  rm -f -- "$bundle_tmp"

  state_entries='[]'
  while IFS= read -r key; do
    state_tmp="$(mktemp "$COORDINATOR_EVIDENCE_ROOT/state.XXXXXX")" || { rm -f -- "$err"; die "live preflight State file could not be created"; }
    if ! aws --profile "$AWS_PROFILE" --region "$REGION" s3api get-object --bucket "$state_bucket" --key "$key" "$state_tmp" >/dev/null 2>"$err"; then
      rm -f -- "$err" "$state_tmp"
      die "live preflight State query failed for $key"
    fi
    state_hash="$(sha256sum "$state_tmp" | awk '{print $1}')"
    state_lineage="$(jq -er '.lineage | select(type == "string" and length > 0)' "$state_tmp")" || { rm -f -- "$err" "$state_tmp"; die "live preflight State lineage is missing for $key"; }
    state_serial="$(jq -er '.serial | numbers' "$state_tmp")" || { rm -f -- "$err" "$state_tmp"; die "live preflight State serial is missing for $key"; }
    state_entries="$(jq -c --arg key "$key" --arg sha "$state_hash" --arg lineage "$state_lineage" --argjson serial "$state_serial" '. + [{key:$key,sha256:$sha,lineage:$lineage,serial:$serial}]' <<<"$state_entries")"
    rm -f -- "$state_tmp"
  done < <(printf '%s\n' dev/terraform.tfstate dev-runtime/terraform.tfstate dev-load-test/terraform.tfstate dev-eks/terraform.tfstate)
  jq -e --argjson expected "$(jq -c '.state_fingerprints' "$PREFLIGHT_PATH")" '($expected | sort_by(.key)) == (. | sort_by(.key))' <<<"$state_entries" >/dev/null || { rm -f -- "$err"; die "live preflight four-State identity differs"; }

  expected_plan="$prior_plan"
  plan_path="$SCRIPT_ROOT/evidence/eks-deploy/$prior_run/create-plan.sha256"
  [[ -f "$plan_path" && ! -L "$plan_path" ]] || { rm -f -- "$err"; die "retained v9 plan identity artifact is missing"; }
  [[ "$(awk 'NF {print $1; exit}' "$plan_path")" == "$expected_plan" ]] || { rm -f -- "$err"; die "retained v9 plan identity differs"; }
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg account "$account" --arg bastion "$bastion" --arg cluster "$cluster" --arg status "$cluster_status" --arg version "$cluster_version" --arg support "$support_status" --arg bucket "$bucket" --arg bundle "$bundle_revision" --argjson states "$state_entries" --arg prior_run "$prior_run" --arg prior_plan "$prior_plan" \
    '{schema_version:"dev-eks-v11-live-identity/v1",captured_at:$captured,account_id:$account,bastion_instance_id:$bastion,bastion_state:"running",bastion_tags:{Environment:"dev",Stack:"dev-eks",Phase:"eks-baseline",Project:"kdt-travelplanner",Name:"kdt-travelplanner-dev-eks-bastion"},cluster_name:$cluster,cluster_status:$status,cluster_version:$version,kubernetes_version_status:$support,monitoring_bucket:$bucket,bundle_revision_sha256:$bundle,state_fingerprints:$states,retained_v9_run_id:$prior_run,retained_v9_plan_sha256:$prior_plan,mutation_started:false}' \
    >"$COORDINATOR_EVIDENCE_ROOT/live-preflight-identity.private.json" || { rm -f -- "$err"; die "live preflight identity evidence could not be serialized"; }
  chmod 0600 "$COORDINATOR_EVIDENCE_ROOT/live-preflight-identity.private.json" || { rm -f -- "$err"; die "live preflight identity evidence permissions could not be secured"; }
  rm -f -- "$err"
}

scope_payload() {
  jq -cn \
    --arg manifest "$EXPECTED_MANIFEST_SHA256" --arg handoff "$EXPECTED_HANDOFF_SHA256" \
    --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg run "$RUN_ID" --arg backend "$EXPECTED_BACKEND_SHA256" \
    --arg capsule "$(sha256sum "$CAPSULE_PATH" | awk '{print $1}')" \
    --arg image "$(jq -er '.backend_image' "$CAPSULE_PATH")" --arg hostname "$(jq -er '.backend_hostname' "$CAPSULE_PATH")" \
    --arg frontend "$(jq -er '.frontend_origin' "$CAPSULE_PATH")" \
    --arg bastion "$(jq -r '.bastion_instance_id' "$PREFLIGHT_PATH")" --arg cluster "$(jq -r '.cluster_name' "$PREFLIGHT_PATH")" \
    --arg prior_run "$(jq -r '.retained_v9_run_id' "$PREFLIGHT_PATH")" --arg prior_plan "$(jq -r '.retained_v9_plan_sha256' "$PREFLIGHT_PATH")" \
    --arg bucket "$(jq -r '.monitoring_bucket' "$PREFLIGHT_PATH")" --arg prefix "$(jq -r '.monitoring_prefix' "$PREFLIGHT_PATH")" \
    --arg bundle "$(jq -r '.bundle_revision_sha256' "$PREFLIGHT_PATH")" \
    --arg helper "$(jq -r '.helper_sha256' "$PREFLIGHT_PATH")" --arg smoke_helper "$(jq -r '.smoke_helper_sha256' "$PREFLIGHT_PATH")" --arg deployer "$(sha256sum "$REPAIR_DEPLOYMENT_RUNNER" | awk '{print $1}')" \
    --arg kubectl "$(jq -r '.kubectl_version' "$PREFLIGHT_PATH")" \
    --arg cluster_version "$(jq -r '.kubernetes_version' "$PREFLIGHT_PATH")" --arg support "$(jq -r '.kubernetes_version_status' "$PREFLIGHT_PATH")" \
    --argjson tags "$(jq -c '.bastion_tags' "$PREFLIGHT_PATH")" --argjson states "$(jq -c '.state_fingerprints' "$PREFLIGHT_PATH")" \
    --arg state_sha "$(jq -r '.dev_eks_state_sha256' "$PREFLIGHT_PATH")" --arg lineage "$(jq -r '.dev_eks_state_lineage' "$PREFLIGHT_PATH")" \
    --argjson serial "$(jq -r '.dev_eks_state_serial' "$PREFLIGHT_PATH")" \
    '{manifest_sha256:$manifest,handoff_sha256:$handoff,account:$account,region:$region,run_id:$run,backend_config_sha256:$backend,capsule_sha256:$capsule,backend_image:$image,backend_hostname:$hostname,frontend_origin:$frontend,bastion_instance_id:$bastion,bastion_tags:$tags,cluster_name:$cluster,kubernetes_version:$cluster_version,kubernetes_version_status:$support,state_fingerprints:$states,retained_v9_run_id:$prior_run,retained_v9_plan_sha256:$prior_plan,monitoring_bucket:$bucket,monitoring_prefix:$prefix,bundle_revision_sha256:$bundle,repair_helper_sha256:$helper,smoke_helper_sha256:$smoke_helper,deployment_runner_sha256:$deployer,kubectl_version:$kubectl,dev_eks_state_sha256:$state_sha,dev_eks_state_lineage:$lineage,dev_eks_state_serial:$serial,actions:["repair existing Bastion kubectl in place","resume retained dev-eks Kubernetes deployment","retain existing resources and one owned Ingress ALB"]}' \
    | jq -cjS .
}

issue_receipt() {
  [[ -n "$RECEIPT_PATH" ]] || die "issue mode requires --authorization-receipt"
  [[ ! -e "$RECEIPT_PATH" && ! -L "$RECEIPT_PATH" ]] || die "refusing to overwrite an existing or symlinked receipt"
  mkdir -p "$COORDINATOR_EVIDENCE_ROOT"
  chmod 0700 "$COORDINATOR_EVIDENCE_ROOT"
  validate_receipt_parent_path "$RECEIPT_PATH"
  local scope_json scope_sha manifest_path
  scope_json="$(scope_payload)"
  scope_sha="$(printf '%s' "$scope_json" | sha256sum | awk '{print $1}')"
  manifest_path="$(ruby -ryaml -e 'puts YAML.safe_load(File.binread(ARGV.fetch(0)), aliases: false).fetch("manifest_path")' "$HANDOFF_PATH")"
  mkdir -p "$(dirname "$RECEIPT_PATH")"
  jq -n \
    --arg manifest "$manifest_path" --arg manifest_sha "$EXPECTED_MANIFEST_SHA256" --arg handoff "$HANDOFF_PATH" --arg handoff_sha "$EXPECTED_HANDOFF_SHA256" \
    --arg run "$RUN_ID" --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg backend_sha "$EXPECTED_BACKEND_SHA256" \
    --arg capsule "$CAPSULE_PATH" --arg capsule_sha "$(sha256sum "$CAPSULE_PATH" | awk '{print $1}')" \
    --arg prior_run "$(jq -r '.retained_v9_run_id' "$PREFLIGHT_PATH")" --arg prior_plan "$(jq -r '.retained_v9_plan_sha256' "$PREFLIGHT_PATH")" \
    --arg bastion "$(jq -r '.bastion_instance_id' "$PREFLIGHT_PATH")" --arg cluster "$(jq -r '.cluster_name' "$PREFLIGHT_PATH")" \
    --arg bucket "$(jq -r '.monitoring_bucket' "$PREFLIGHT_PATH")" --arg prefix "$(jq -r '.monitoring_prefix' "$PREFLIGHT_PATH")" --arg bundle "$(jq -r '.bundle_revision_sha256' "$PREFLIGHT_PATH")" \
    --arg helper "$(jq -r '.helper_sha256' "$PREFLIGHT_PATH")" --arg smoke_helper "$(jq -r '.smoke_helper_sha256' "$PREFLIGHT_PATH")" --arg deployer "$(sha256sum "$REPAIR_DEPLOYMENT_RUNNER" | awk '{print $1}')" --arg kubectl "$(jq -r '.kubectl_version' "$PREFLIGHT_PATH")" --arg cluster_version "$(jq -r '.kubernetes_version' "$PREFLIGHT_PATH")" --arg support "$(jq -r '.kubernetes_version_status' "$PREFLIGHT_PATH")" --arg state_sha "$(jq -r '.dev_eks_state_sha256' "$PREFLIGHT_PATH")" \
    --argjson tags "$(jq -c '.bastion_tags' "$PREFLIGHT_PATH")" --argjson states "$(jq -c '.state_fingerprints' "$PREFLIGHT_PATH")" \
    --arg image "$(jq -er '.backend_image' "$CAPSULE_PATH")" --arg hostname "$(jq -er '.backend_hostname' "$CAPSULE_PATH")" --arg frontend "$(jq -er '.frontend_origin' "$CAPSULE_PATH")" \
    --arg lineage "$(jq -r '.dev_eks_state_lineage' "$PREFLIGHT_PATH")" --argjson serial "$(jq -r '.dev_eks_state_serial' "$PREFLIGHT_PATH")" --arg scope "$scope_sha" \
    --arg expires "$(date -u -v+2H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+2 hours' +%Y-%m-%dT%H:%M:%SZ)" \
    '{schema_version:"dev-eks-repair-authorization/v1",handoff_schema_version:"plan-handoff/v1",manifest_schema_version:"plan-manifest/v3",plan_id:"dev-eks-deployment-automation",plan_version:11,manifest_path:$manifest,manifest_sha256:$manifest_sha,handoff_path:$handoff,handoff_sha256:$handoff_sha,run_id:$run,retained_v9_run_id:$prior_run,retained_v9_plan_sha256:$prior_plan,expected_account_id:$account,expected_region:$region,terraform_backend_key:"dev-eks/terraform.tfstate",terraform_backend_config_sha256:$backend_sha,input_capsule_path:$capsule,input_capsule_sha256:$capsule_sha,backend_image:$image,backend_hostname:$hostname,frontend_origin:$frontend,bastion_instance_id:$bastion,bastion_tags:$tags,cluster_name:$cluster,kubernetes_version:$cluster_version,kubernetes_version_status:$support,state_fingerprints:$states,monitoring_bucket:$bucket,monitoring_prefix:$prefix,bundle_revision_sha256:$bundle,runtime_values_sha256:null,repair_helper_sha256:$helper,smoke_helper_sha256:$smoke_helper,deployment_runner_sha256:$deployer,kubectl_version:$kubectl,dev_eks_state_sha256:$state_sha,dev_eks_state_lineage:$lineage,dev_eks_state_serial:$serial,protected_state_keys:["dev/terraform.tfstate","dev-runtime/terraform.tfstate","dev-load-test/terraform.tfstate","dev-eks/terraform.tfstate"],repair_scope_sha256:$scope,expires_at:$expires,status:"pending",single_use:true,render_sha256:null,permitted_actions:["repair existing Bastion kubectl in place","resume retained dev-eks Kubernetes deployment","retain existing resources and one owned Ingress ALB"],forbidden_actions:["Terraform plan/apply/destroy","Bastion replacement","IAM mutation","Cloudflare mutation","Kubernetes delete","protected State write","shared lifecycle cleanup"],paid_approval:{status:"pending",action:("APPLY DEV-EKS REPAIR-AND-RESUME " + $scope),scope_sha256:$scope}}' >"$RECEIPT_PATH" || die "repair receipt creation failed"
  chmod 0600 "$RECEIPT_PATH"
  printf 'status=pending approval=APPLY DEV-EKS REPAIR-AND-RESUME %s\n' "$scope_sha"
}

receipt_scope_payload() {
  jq -cjS '{manifest_sha256:.manifest_sha256,handoff_sha256:.handoff_sha256,account:.expected_account_id,region:.expected_region,run_id:.run_id,backend_config_sha256:.terraform_backend_config_sha256,capsule_sha256:.input_capsule_sha256,backend_image:.backend_image,backend_hostname:.backend_hostname,frontend_origin:.frontend_origin,bastion_instance_id:.bastion_instance_id,bastion_tags:.bastion_tags,cluster_name:.cluster_name,kubernetes_version:.kubernetes_version,kubernetes_version_status:.kubernetes_version_status,state_fingerprints:.state_fingerprints,retained_v9_run_id:.retained_v9_run_id,retained_v9_plan_sha256:.retained_v9_plan_sha256,monitoring_bucket:.monitoring_bucket,monitoring_prefix:.monitoring_prefix,bundle_revision_sha256:.bundle_revision_sha256,repair_helper_sha256:.repair_helper_sha256,smoke_helper_sha256:.smoke_helper_sha256,deployment_runner_sha256:.deployment_runner_sha256,kubectl_version:.kubectl_version,dev_eks_state_sha256:.dev_eks_state_sha256,dev_eks_state_lineage:.dev_eks_state_lineage,dev_eks_state_serial:.dev_eks_state_serial,actions:.permitted_actions}' "$RECEIPT_PATH"
}

parse_receipt_epoch() {
  local value="$1"
  date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$value" +%s 2>/dev/null || date -u -d "$value" +%s 2>/dev/null
}

validate_active_receipt() {
  local manifest_path repair_sha smoke_sha deployer_sha scope expected_scope expected expires expires_epoch
  [[ -f "$RECEIPT_PATH" && ! -L "$RECEIPT_PATH" ]] || die "active repair receipt is not a regular file"
  [[ "$(stat -f '%Lp' "$RECEIPT_PATH" 2>/dev/null || stat -c '%a' "$RECEIPT_PATH" 2>/dev/null)" == "600" ]] || die "active repair receipt must be mode 0600"
  manifest_path="$(ruby -ryaml -e 'puts YAML.safe_load(File.binread(ARGV.fetch(0)), aliases: false).fetch("manifest_path")' "$HANDOFF_PATH")" || die "v11 manifest path could not be resolved"
  repair_sha="$(sha256sum "$REPAIR_HELPER" | awk '{print $1}')"
  smoke_sha="$(sha256sum "$SMOKE_HELPER" | awk '{print $1}')"
  deployer_sha="$(sha256sum "$REPAIR_DEPLOYMENT_RUNNER" | awk '{print $1}')"
  scope="$(jq -er '.repair_scope_sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$RECEIPT_PATH")" || die "active repair scope is missing"
  expected_scope="$(receipt_scope_payload | sha256sum | awk '{print $1}')" || die "active repair scope could not be recomputed"
  [[ "$scope" == "$expected_scope" ]] || die "active repair scope does not match its bound receipt fields"
  jq -e \
    --arg manifest "$manifest_path" --arg manifest_sha "$EXPECTED_MANIFEST_SHA256" --arg handoff "$HANDOFF_PATH" --arg handoff_sha "$EXPECTED_HANDOFF_SHA256" \
    --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg run "$RUN_ID" --arg backend "$EXPECTED_BACKEND_SHA256" --arg capsule "$EXPECTED_CAPSULE_SHA256" --arg capsule_path "$CAPSULE_PATH" \
    --arg image "$(jq -er '.backend_image' "$CAPSULE_PATH")" --arg hostname "$(jq -er '.backend_hostname' "$CAPSULE_PATH")" --arg frontend "$(jq -er '.frontend_origin' "$CAPSULE_PATH")" \
    --arg repair "$repair_sha" --arg smoke "$smoke_sha" --arg deployer "$deployer_sha" --arg scope "$scope" '
      type == "object" and .schema_version == "dev-eks-repair-authorization/v1" and
      .handoff_schema_version == "plan-handoff/v1" and .manifest_schema_version == "plan-manifest/v3" and
      .plan_id == "dev-eks-deployment-automation" and .plan_version == 11 and
      .manifest_path == $manifest and .manifest_sha256 == $manifest_sha and .handoff_path == $handoff and .handoff_sha256 == $handoff_sha and
      .run_id == $run and
      (.retained_v9_run_id | type == "string" and test("^[0-9]{8}T[0-9]{6}Z-[0-9]+$")) and
      (.retained_v9_plan_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
      .status == "active" and .single_use == true and .expected_account_id == $account and .expected_region == $region and
      .terraform_backend_key == "dev-eks/terraform.tfstate" and .terraform_backend_config_sha256 == $backend and
      .input_capsule_path == $capsule_path and .input_capsule_sha256 == $capsule and .backend_image == $image and .backend_hostname == $hostname and .frontend_origin == $frontend and
      (.bastion_instance_id | type == "string" and test("^i-[0-9a-f]+$")) and (.cluster_name | type == "string" and length > 0) and
      (.monitoring_bucket | type == "string" and test("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")) and (.monitoring_prefix | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$")) and
      (.bundle_revision_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
      ((.runtime_values_sha256 == null) or (.completion_lease == true and .continuity_verified == true and (.runtime_values_sha256 | type == "string" and test("^[0-9a-f]{64}$")))) and
      .repair_helper_sha256 == $repair and .smoke_helper_sha256 == $smoke and
      ((.deployment_runner_sha256 == $deployer) or (.completion_lease == true and .continuity_verified == true)) and .kubectl_version == "1.35.6" and
      (.dev_eks_state_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and (.dev_eks_state_lineage | type == "string" and length > 0) and (.dev_eks_state_serial | type == "number" and . >= 0 and . == floor) and
      (.kubernetes_version == "1.35") and (.kubernetes_version_status == "STANDARD_SUPPORT") and
      (.bastion_tags | type == "object" and .Environment == "dev" and .Stack == "dev-eks" and .Phase == "eks-baseline" and .Project == "kdt-travelplanner" and .Name == "kdt-travelplanner-dev-eks-bastion") and
      (.state_fingerprints | type == "array" and length == 4 and (map(.key) | sort) == ["dev-eks/terraform.tfstate","dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"]) and
      (.protected_state_keys | type == "array" and sort == ["dev-eks/terraform.tfstate","dev-load-test/terraform.tfstate","dev-runtime/terraform.tfstate","dev/terraform.tfstate"]) and
      (.permitted_actions | type == "array" and sort == ["repair existing Bastion kubectl in place","resume retained dev-eks Kubernetes deployment","retain existing resources and one owned Ingress ALB"]) and
      (.forbidden_actions | type == "array" and sort == ["Bastion replacement","Cloudflare mutation","IAM mutation","Kubernetes delete","Terraform plan/apply/destroy","protected State write","shared lifecycle cleanup"]) and
      ((.render_sha256 == null) or (.completion_lease == true and .continuity_verified == true and (.render_sha256 | type == "string" and test("^[0-9a-f]{64}$")))) and
      .paid_approval.status == "approved" and .paid_approval.action == ("APPLY DEV-EKS REPAIR-AND-RESUME " + $scope) and .paid_approval.scope_sha256 == $scope
    ' "$RECEIPT_PATH" >/dev/null || die "active v11 repair receipt binding or scope is invalid"
  expires="$(jq -er '.expires_at | select(type == "string")' "$RECEIPT_PATH")" || die "active repair receipt expiry is missing"
  expires_epoch="$(parse_receipt_epoch "$expires")" || die "active repair receipt expiry is malformed"
  (( expires_epoch > $(date +%s) )) || die "active repair receipt is expired"
  [[ -n "$PREFLIGHT_PATH" ]] || die "active repair receipt requires the same read-only preflight JSON"
  jq -e --slurpfile preflight "$PREFLIGHT_PATH" '
    ($preflight | length == 1) and
    .bastion_instance_id == $preflight[0].bastion_instance_id and
    .cluster_name == $preflight[0].cluster_name and
    .monitoring_bucket == $preflight[0].monitoring_bucket and
    .monitoring_prefix == $preflight[0].monitoring_prefix and
    .retained_v9_run_id == $preflight[0].retained_v9_run_id and
    .retained_v9_plan_sha256 == $preflight[0].retained_v9_plan_sha256 and
    .bundle_revision_sha256 == $preflight[0].bundle_revision_sha256 and
    .repair_helper_sha256 == $preflight[0].helper_sha256 and
    .smoke_helper_sha256 == $preflight[0].smoke_helper_sha256 and
    .kubectl_version == $preflight[0].kubectl_version and
    .kubernetes_version == $preflight[0].kubernetes_version and
    .kubernetes_version_status == $preflight[0].kubernetes_version_status and
    .bastion_tags == $preflight[0].bastion_tags and
    .state_fingerprints == $preflight[0].state_fingerprints and
    .dev_eks_state_sha256 == $preflight[0].dev_eks_state_sha256 and
    .dev_eks_state_lineage == $preflight[0].dev_eks_state_lineage and
    .dev_eks_state_serial == $preflight[0].dev_eks_state_serial
  ' "$RECEIPT_PATH" >/dev/null || die "active repair receipt does not match the exact preflight scope"
}

validate_prior_explicit_consent() {
  [[ "$PRIOR_APPROVAL_SCOPE" =~ ^[0-9a-f]{64}$ ]] || die "prior explicit approval scope is missing or malformed"
  [[ -f "$PRIOR_APPROVAL_RECEIPT" && ! -L "$PRIOR_APPROVAL_RECEIPT" ]] || die "prior explicit approval receipt is missing"
  [[ "$(stat -f '%Lp' "$PRIOR_APPROVAL_RECEIPT" 2>/dev/null || stat -c '%a' "$PRIOR_APPROVAL_RECEIPT" 2>/dev/null)" == "600" ]] || die "prior explicit approval receipt must be mode 0600"
  jq -e \
    --arg scope "$PRIOR_APPROVAL_SCOPE" --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg cluster "$CLUSTER_NAME" \
    'type == "object" and .schema_version == "dev-eks-repair-authorization/v1" and .status == "consumed" and
     .repair_scope_sha256 == $scope and .expected_account_id == $account and .expected_region == $region and .cluster_name == $cluster and
     (.bastion_instance_id | type == "string" and test("^i-[0-9a-f]+$")) and
     (.permitted_actions | type == "array" and sort == ["repair existing Bastion kubectl in place","resume retained dev-eks Kubernetes deployment","retain existing resources and one owned Ingress ALB"]) and
     (.forbidden_actions | type == "array" and sort == ["Bastion replacement","Cloudflare mutation","IAM mutation","Kubernetes delete","Terraform plan/apply/destroy","protected State write","shared lifecycle cleanup"]) and
     (.paid_approval.status == "approved" and .paid_approval.action == ("APPLY DEV-EKS REPAIR-AND-RESUME " + $scope))' \
    "$PRIOR_APPROVAL_RECEIPT" >/dev/null || die "prior explicit approval does not prove the unchanged action scope"
}

mark_completion_lease() {
  local updated
  updated="$(mktemp "${RECEIPT_PATH}.completion.XXXXXX")" || die "could not allocate completion lease"
  jq --arg prior "$PRIOR_APPROVAL_RECEIPT" --arg prior_scope "$PRIOR_APPROVAL_SCOPE" \
    '.completion_lease=true | .continuity_verified=true | .prior_user_approval_receipt=$prior | .prior_user_approval_scope_sha256=$prior_scope | .attempt_budget=3 | .repair_cycle_budget=2' \
    "$RECEIPT_PATH" >"$updated" || { rm -f -- "$updated"; die "completion lease creation failed"; }
  chmod 0600 "$updated"
  mv -f -- "$updated" "$RECEIPT_PATH"
}

validate_handoff
validate_capsule
if [[ "$MODE" == "preflight" ]]; then
  capture_live_preflight
  validate_preflight
  printf 'status=preflight-ready path=%s\n' "$PREFLIGHT_PATH"
elif [[ "$MODE" == "completion-issue" ]]; then
  [[ -n "$PREFLIGHT_PATH" ]] || die "completion-issue requires --preflight-json"
  [[ -n "$PRIOR_APPROVAL_RECEIPT" ]] || die "completion-issue requires --prior-authorization-receipt"
  validate_prior_explicit_consent
  validate_preflight
  issue_receipt
  mark_completion_lease
  printf 'status=pending-completion receipt=%s prior_approval_scope=%s\n' "$RECEIPT_PATH" "$PRIOR_APPROVAL_SCOPE"
elif [[ "$MODE" == "issue" ]]; then
  [[ -n "$PREFLIGHT_PATH" ]] || die "issue mode requires --preflight-json"
  validate_preflight
  issue_receipt
else
  run_repair_and_resume() {
    [[ -n "$RECEIPT_PATH" && -f "$RECEIPT_PATH" && ! -L "$RECEIPT_PATH" ]] || die "run mode requires the exact repair receipt"
    [[ "$(stat -f '%Lp' "$RECEIPT_PATH" 2>/dev/null || stat -c '%a' "$RECEIPT_PATH" 2>/dev/null)" == "600" ]] || die "repair receipt must be mode 0600"
    [[ "$(jq -r '.schema_version' "$RECEIPT_PATH")" == "dev-eks-repair-authorization/v1" ]] || die "receipt is not v11 repair authorization"
    local scope expected updated bucket prefix remote_key remote_dir command parameters command_id invocation status
    scope="$(jq -er '.repair_scope_sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$RECEIPT_PATH")" || die "receipt scope is missing"
    expected="APPLY DEV-EKS REPAIR-AND-RESUME $scope"
    if [[ "$(jq -r '.status' "$RECEIPT_PATH" 2>/dev/null || true)" == pending ]]; then
      if jq -e '.completion_lease == true and .continuity_verified == true' "$RECEIPT_PATH" >/dev/null 2>&1; then
        [[ "$MODE" == "completion-run" ]] || die "completion lease requires completion-run mode"
        [[ -n "$PRIOR_APPROVAL_RECEIPT" ]] || die "completion-run requires --prior-authorization-receipt"
        validate_prior_explicit_consent
      else
        [[ "$APPROVAL" == "$expected" ]] || die "exact repair approval does not match the receipt scope"
      fi
      updated="$(mktemp "${RECEIPT_PATH}.active.XXXXXX")" || die "could not allocate active receipt"
      jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg action "$expected" '.status="active" | .paid_approval.status="approved" | .paid_approval.action=$action | .approved_at=$now' "$RECEIPT_PATH" >"$updated" || { rm -f -- "$updated"; die "could not activate repair receipt"; }
      chmod 0600 "$updated"
      mv -f -- "$updated" "$RECEIPT_PATH"
    fi
    [[ "$(jq -r '.status' "$RECEIPT_PATH")" == active ]] || die "repair receipt is not active"
    RUN_EXECUTION_STARTED=true
    validate_preflight
    if jq -e '.completion_lease == true and .continuity_verified == true' "$RECEIPT_PATH" >/dev/null 2>&1; then
      validate_prior_explicit_consent
    fi
    validate_active_receipt
    validate_live_preflight_identity
    bucket="$(jq -er '.monitoring_bucket' "$RECEIPT_PATH")"
    prefix="$(jq -er '.monitoring_prefix' "$RECEIPT_PATH")"
    remote_key="$prefix/runs/$RUN_ID/repair/repair-dev-eks-bastion.sh"
    remote_dir="/var/tmp/travel-planner-dev-eks-$RUN_ID/repair"
    aws --profile "$AWS_PROFILE" --region "$REGION" s3 cp "$REPAIR_HELPER" "s3://$bucket/$remote_key" --sse AES256 >/dev/null || die "repair helper upload failed"
    printf -v command 'set -eu; mkdir -p %q; chmod 700 %q; export AWS_REGION=%q AWS_DEFAULT_REGION=%q; aws s3 cp %q %q; test "$(sha256sum %q | awk '\''{print $1}'\'')" = %q; chmod 700 %q; bash %q --kubectl-version %q --cluster-name %q --region %q --expected-account-id %q --work-dir %q' \
      "$remote_dir" "$remote_dir" "$REGION" "$REGION" "s3://$bucket/$remote_key" "$remote_dir/repair-dev-eks-bastion.sh" "$remote_dir/repair-dev-eks-bastion.sh" "$(jq -r '.repair_helper_sha256' "$RECEIPT_PATH")" "$remote_dir/repair-dev-eks-bastion.sh" "$remote_dir/repair-dev-eks-bastion.sh" "$(jq -r '.kubectl_version' "$RECEIPT_PATH")" "$(jq -r '.cluster_name' "$RECEIPT_PATH")" "$REGION" "$EXPECTED_ACCOUNT_ID" "$remote_dir"
    parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')" || die "repair SSM parameters could not be serialized"
    jq -e 'type == "object" and (.commands | type == "array") and (.commands | length == 1) and (.commands[0] | type == "string" and length > 0)' <<<"$parameters" >/dev/null || die "repair SSM parameters shape is invalid"
    if ! command_id="$(aws --profile "$AWS_PROFILE" --region "$REGION" ssm send-command --document-name AWS-RunShellScript --instance-ids "$(jq -r '.bastion_instance_id' "$RECEIPT_PATH")" --parameters "$parameters" --comment "dev-eks-$RUN_ID-repair" --query Command.CommandId --output text 2>/dev/null)"; then
      write_ssm_failure_evidence "submission_failed" "send-command request failed"
      die "repair SSM command submission failed"
    fi
    if [[ ! "$command_id" =~ ^[A-Za-z0-9-]{36}$ ]]; then
      write_ssm_failure_evidence "invalid_command_id" "send-command returned an invalid command id"
      die "repair SSM command id is invalid"
    fi
    local deadline=$((SECONDS + SSM_TIMEOUT_SECONDS)) poll_error
    while ((SECONDS < deadline)); do
      poll_error="$(mktemp "$COORDINATOR_EVIDENCE_ROOT/ssm-poll-error.XXXXXX")" || die "SSM poll error file could not be created"
      if ! invocation="$(aws --profile "$AWS_PROFILE" --region "$REGION" ssm get-command-invocation --command-id "$command_id" --instance-id "$(jq -r '.bastion_instance_id' "$RECEIPT_PATH")" --output json 2>"$poll_error")"; then
        if grep -Eqi 'AccessDenied|UnauthorizedOperation|not authorized|AccessDeniedException' "$poll_error"; then
          rm -f -- "$poll_error"
          write_ssm_failure_evidence "AccessDenied" "SSM invocation lookup permission denied" "$command_id"
          die "SSM invocation lookup was denied by IAM"
        fi
        if grep -q 'InvocationDoesNotExist' "$poll_error"; then
          rm -f -- "$poll_error"
          sleep 5
          continue
        fi
        rm -f -- "$poll_error"
        write_ssm_failure_evidence "lookup_failed" "SSM invocation lookup failed" "$command_id"
        die "SSM invocation lookup failed"
      fi
      rm -f -- "$poll_error"
      if [[ -z "$invocation" ]]; then
        write_ssm_failure_evidence "empty_response" "SSM invocation returned an empty response" "$command_id"
        die "SSM invocation response was empty"
      fi
      if ! jq -e 'type == "object" and (.Status | type == "string")' <<<"$invocation" >/dev/null; then
        write_ssm_failure_evidence "invalid_response" "SSM invocation response schema was invalid" "$command_id"
        die "SSM invocation response schema was invalid"
      fi
      if [[ "$(jq -r '.CommandId // empty' <<<"$invocation")" != "$command_id" ]]; then
        write_ssm_failure_evidence "invalid_response" "SSM invocation command identity differed" "$command_id"
        die "SSM invocation command identity differed"
      fi
      if [[ "$(jq -r '.InstanceId // empty' <<<"$invocation")" != "$(jq -r '.bastion_instance_id' "$RECEIPT_PATH")" ]]; then
        write_ssm_failure_evidence "invalid_response" "SSM invocation instance identity differed" "$command_id"
        die "SSM invocation instance identity differed"
      fi
      if [[ "$(jq -r '.Status' <<<"$invocation")" == "" ]]; then
        write_ssm_failure_evidence "invalid_response" "SSM invocation status was empty" "$command_id"
        die "SSM invocation status was empty"
      fi
      if [[ "$(jq -r '.Status' <<<"$invocation")" == "Pending" || "$(jq -r '.Status' <<<"$invocation")" == "InProgress" || "$(jq -r '.Status' <<<"$invocation")" == "Delayed" ]]; then
        sleep 5
        continue
      fi
      status="$(jq -r '.Status // empty' <<<"$invocation")"
      case "$status" in
        Success)
          if ! jq -e '.ResponseCode == 0' <<<"$invocation" >/dev/null; then
            write_ssm_failure_evidence "Failed" "Bastion repair returned a non-zero response" "$(jq -r '.CommandId // empty' <<<"$invocation")" "$(jq -r '.ResponseCode // empty' <<<"$invocation")"
            die "Bastion repair returned a non-zero response"
          fi
          break
          ;;
        Failed|Cancelled|TimedOut|Cancelling)
          write_ssm_failure_evidence "$status" "Bastion repair returned terminal SSM status" "$(jq -r '.CommandId // empty' <<<"$invocation")" "$(jq -r '.ResponseCode // empty' <<<"$invocation")"
          die "Bastion kubectl repair failed with status $status" ;;
        *)
          write_ssm_failure_evidence "unknown" "Bastion repair returned an unknown SSM status" "$(jq -r '.CommandId // empty' <<<"$invocation")" "$(jq -r '.ResponseCode // empty' <<<"$invocation")"
          die "Bastion repair returned unknown SSM status" ;;
      esac
    done
    if (( SECONDS >= deadline )); then
      write_ssm_failure_evidence "TimedOut" "Bastion repair SSM polling timed out" "$command_id"
      die "Bastion repair SSM polling timed out"
    fi
    DEV_EKS_DEFER_CNAME_OUTPUT=true bash "$DEPLOYER" --mode resume --resume-from prepare --resume-run-id "$(jq -er '.retained_v9_run_id' "$RECEIPT_PATH")" --run-id "$RUN_ID" --skip-terraform-apply --non-interactive --aws-profile "$AWS_PROFILE" --region "$REGION" --expected-account-id "$EXPECTED_ACCOUNT_ID" --backend-image "$(jq -er '.backend_image' "$CAPSULE_PATH")" --backend-hostname "$(jq -er '.backend_hostname' "$CAPSULE_PATH")" --frontend-origin "$(jq -er '.frontend_origin' "$CAPSULE_PATH")" --action-values-capsule "$CAPSULE_PATH" --authorization-receipt "$RECEIPT_PATH" --repair-preflight-json "$PREFLIGHT_PATH" --plan-handoff "$HANDOFF_PATH"
    final_cname_path="$SCRIPT_ROOT/evidence/eks-deploy/$RUN_ID/final-cname.private.txt"
    [[ -f "$final_cname_path" && ! -L "$final_cname_path" ]] || die "deployer did not retain the final private CNAME artifact"
    [[ "$(stat -f '%Lp' "$final_cname_path" 2>/dev/null || stat -c '%a' "$final_cname_path" 2>/dev/null)" == "600" ]] || die "final private CNAME artifact must be mode 0600"
    final_cname_line="$(awk 'NF {print; count++} END {if (count != 1) exit 1}' "$final_cname_path")" || die "final private CNAME artifact must contain exactly one line"
    [[ "$final_cname_line" =~ ^CLOUDFLARE_CNAME_TARGET=([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]] || die "final private CNAME artifact is invalid"
    printf '%s\n' "$final_cname_line"
  }
  run_repair_and_resume
fi
