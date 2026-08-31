#!/usr/bin/env bash
set -euo pipefail

# SCRUM-53 creation-only coordinator. It owns canonical inputs, one fresh
# dev-eks saved plan and the v9 paid-action receipt, then delegates the
# approved create/deploy path to deploy-dev-eks.sh. It has no retirement or
# Cloudflare action surface.

umask 077

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TERRAFORM_ROOT="$SCRIPT_ROOT/infra/environments/dev-eks"
CAPSULE_DEFAULT="$SCRIPT_ROOT/evidence/eks-deploy/20260824T133440Z-15798/action-values.json"
MODE="run"
AWS_PROFILE="kdt-travel-terraform"
IAM_ADMIN_PROFILE="${DEV_EKS_IAM_ADMIN_PROFILE:-kdt-travel-admin}"
REGION="ap-northeast-2"
CAPSULE_PATH="$CAPSULE_DEFAULT"
CAPSULE_REALPATH=""
RUN_ID=""
APPROVAL=""
REPORT_ROOT_OVERRIDE=""
PLAN_HANDOFF_PATH="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v9.yaml"
PLAN_HANDOFF_REALPATH=""
PLAN_HANDOFF_SHA256=""
PLAN_MANIFEST_REALPATH=""
PLAN_MANIFEST_SHA256=""
PLAN_ID=""
PLAN_VERSION=""
OFFLINE_TEST=false

# These values are the authenticated v9 handoff contract.  The handoff and
# manifest are not allowed to authenticate themselves by merely repeating a
# hash from their own contents.
EXPECTED_PLAN_HANDOFF_SHA256="65c976f1d47c9377c534913257285a896a20d5ee2e8d0fce9fa0169f54dbfd87"
EXPECTED_PLAN_MANIFEST_SHA256="0dae12f25aeb0a50ce7d5661aa2497f51c21c47f43f69f5df3b4f0d46de8c392"
EXPECTED_BACKEND_CONFIG_SHA256="86af5e85a52d52f36f4f64274d238e68985e5084f1554eab9b6364e9f2907515"
EXPECTED_CAPSULE_SHA256="3c0a636a230247a10c785822487df1ca8b5a1cfeead4d695f54afdc98d4f44f8"

usage() {
  cat >&2 <<'USAGE'
Usage: run-dev-eks-create-and-deploy.sh [--mode plan|run]
  [--aws-profile <profile>] [--region ap-northeast-2]
  [--iam-admin-profile <read-only admin profile>]
  [--action-values-capsule <mode-0600 JSON>]
  [--plan-handoff <exact immutable handoff-v9.yaml>]
  [--run-id <YYYYMMDDTHHMMSSZ-pid>]
  [--approval "APPLY DEV-EKS CREATE-AND-RETAIN <plan-sha256>"]
  [--report-root <test-only private directory>] [--offline-test]

plan mode creates one private saved plan and a pending v9 receipt, then
prints the exact paid-resource approval. run mode consumes that same plan
and receipt only when the exact approval is supplied.
USAGE
}

die() { printf 'status=failed reason=%s\n' "$1" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --mode) MODE="${2:?missing value for --mode}"; shift 2 ;;
    --aws-profile) AWS_PROFILE="${2:?missing value for --aws-profile}"; shift 2 ;;
    --iam-admin-profile) IAM_ADMIN_PROFILE="${2:?missing value for --iam-admin-profile}"; shift 2 ;;
    --region) REGION="${2:?missing value for --region}"; shift 2 ;;
    --action-values-capsule) CAPSULE_PATH="${2:?missing value for --action-values-capsule}"; shift 2 ;;
    --plan-handoff) PLAN_HANDOFF_PATH="${2:?missing value for --plan-handoff}"; shift 2 ;;
    --run-id) RUN_ID="${2:?missing value for --run-id}"; shift 2 ;;
    --approval) APPROVAL="${2:?missing value for --approval}"; shift 2 ;;
    --report-root) REPORT_ROOT_OVERRIDE="${2:?missing value for --report-root}"; shift 2 ;;
    --offline-test) OFFLINE_TEST=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument" ;;
  esac
done

[[ "$MODE" =~ ^(plan|run)$ ]] || die "mode must be plan or run"
[[ "$REGION" == "ap-northeast-2" ]] || die "region must be ap-northeast-2 for this dev contract"
if [[ "$OFFLINE_TEST" == true ]]; then
  [[ "$AWS_PROFILE" == "offline" && -n "$REPORT_ROOT_OVERRIDE" ]] || die "offline-test requires the offline AWS profile and an explicit report root"
fi
[[ -f "$CAPSULE_PATH" && ! -L "$CAPSULE_PATH" ]] || die "canonical action-values capsule is missing"
[[ "$(stat -f '%Lp' "$CAPSULE_PATH" 2>/dev/null || stat -c '%a' "$CAPSULE_PATH" 2>/dev/null)" == "600" ]] || die "canonical action-values capsule must have mode 0600"

for command_name in aws jq sha256sum terraform mktemp ruby; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
done

validate_plan_handoff() {
  [[ -f "$PLAN_HANDOFF_PATH" && ! -L "$PLAN_HANDOFF_PATH" ]] || die "exact v9 plan handoff is missing"
  PLAN_HANDOFF_REALPATH="$(cd "$(dirname "$PLAN_HANDOFF_PATH")" && pwd)/$(basename "$PLAN_HANDOFF_PATH")"
  local canonical_handoff canonical_manifest details
  canonical_handoff="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/handoff-v9.yaml"
  canonical_manifest="$SCRIPT_ROOT/.codex/plans/dev-eks-deployment-automation/plan-v9.yaml"
  if [[ "$OFFLINE_TEST" == false ]]; then
    [[ "$PLAN_HANDOFF_REALPATH" == "$canonical_handoff" ]] || die "plan handoff path is not the authenticated v9 handoff"
  else
    [[ "$PLAN_HANDOFF_REALPATH" == "$canonical_handoff" || ( -n "$REPORT_ROOT_OVERRIDE" && "$PLAN_HANDOFF_REALPATH" == "$REPORT_ROOT_OVERRIDE"/* ) ]] || die "plan handoff path is not the authenticated v9 handoff"
  fi
  PLAN_HANDOFF_SHA256="$(sha256sum "$PLAN_HANDOFF_REALPATH" | awk '{print $1}')"
  [[ "$PLAN_HANDOFF_SHA256" == "$EXPECTED_PLAN_HANDOFF_SHA256" ]] || die "canonical v9 plan handoff hash does not match the authenticated plan"
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
  PLAN_ID="$(jq -er '.plan_id | select(type == "string")' <<<"$details")" || die "v9 handoff plan id is missing"
  PLAN_VERSION="$(jq -er '.version | select(type == "number" and floor == .)' <<<"$details")" || die "v9 handoff version is malformed"
  PLAN_MANIFEST_REALPATH="$(jq -er '.manifest_path | select(type == "string")' <<<"$details")" || die "v9 handoff manifest path is missing"
  PLAN_MANIFEST_SHA256="$(jq -er '.manifest_sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' <<<"$details")" || die "v9 handoff manifest hash is malformed"
  [[ "$PLAN_MANIFEST_SHA256" == "$EXPECTED_PLAN_MANIFEST_SHA256" ]] || die "canonical v9 plan manifest hash does not match the authenticated plan"
  jq -e --arg root "$SCRIPT_ROOT" --arg handoff_schema "plan-handoff/v1" --arg manifest_schema "plan-manifest/v3" --arg manifest "$canonical_manifest" --arg actual "$PLAN_MANIFEST_SHA256" --arg offline_root "${REPORT_ROOT_OVERRIDE:-}" '
    .handoff_schema == $handoff_schema and .manifest_schema == $manifest_schema and
    .plan_id == "dev-eks-deployment-automation" and .version == 9 and .status == "ready" and .immutable == true and
    .task_root == $root and (.manifest_path == $manifest or ($offline_root != "" and (.manifest_path | startswith($offline_root + "/")))) and .manifest_sha256 == $actual and
    .actual_manifest_sha256 == $actual and
    .manifest_identity.schema == $manifest_schema and .manifest_identity.plan_id == "dev-eks-deployment-automation" and
    .manifest_identity.version == 9 and .manifest_identity.status == "ready" and .manifest_identity.immutable == true
  ' <<<"$details" >/dev/null || die "v9 handoff or manifest identity/hash is invalid"
}

validate_plan_handoff

BACKEND_IMAGE="$(jq -er '.backend_image | select(type == "string")' "$CAPSULE_PATH")" || die "canonical backend image is missing"
BACKEND_HOSTNAME="$(jq -er '.backend_hostname | select(type == "string")' "$CAPSULE_PATH")" || die "canonical backend hostname is missing"
FRONTEND_ORIGIN="$(jq -er '.frontend_origin | select(type == "string")' "$CAPSULE_PATH")" || die "canonical frontend origin is missing"
[[ "$BACKEND_IMAGE" =~ ^([0-9]{12})\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || die "canonical backend image is not an immutable ECR reference"
EXPECTED_ACCOUNT_ID="${BASH_REMATCH[1]}"
[[ "$BACKEND_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "canonical backend hostname is invalid"
[[ "$FRONTEND_ORIGIN" =~ ^https://[a-z0-9.-]+$ ]] || die "canonical frontend origin is invalid"
CAPSULE_SHA256="$(sha256sum "$CAPSULE_PATH" | awk '{print $1}')"
CAPSULE_REALPATH="$(cd "$(dirname "$CAPSULE_PATH")" && pwd)/$(basename "$CAPSULE_PATH")"
[[ -f "$TERRAFORM_ROOT/backend.hcl" && ! -L "$TERRAFORM_ROOT/backend.hcl" ]] || die "dev-eks backend configuration is missing"
BACKEND_CONFIG_SHA256="$(sha256sum "$TERRAFORM_ROOT/backend.hcl" | awk '{print $1}')"
[[ "$BACKEND_CONFIG_SHA256" == "$EXPECTED_BACKEND_CONFIG_SHA256" ]] || die "dev-eks backend configuration hash does not match the authenticated plan"
CANONICAL_CAPSULE_REALPATH="$(cd "$(dirname "$CAPSULE_DEFAULT")" && pwd)/$(basename "$CAPSULE_DEFAULT")"
if [[ "$OFFLINE_TEST" == false ]]; then
  [[ "$CAPSULE_REALPATH" == "$CANONICAL_CAPSULE_REALPATH" ]] || die "production create mode requires the canonical action-values capsule path"
  [[ "$CAPSULE_SHA256" == "$EXPECTED_CAPSULE_SHA256" ]] || die "canonical action-values capsule hash does not match the authenticated plan"
fi
jq -e --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" '
  type == "object" and
  (.vpc_id | type == "string" and test("^vpc-[0-9a-f]+$")) and
  (.public_subnet_ids | type == "array" and length >= 2 and all(.[]; type == "string" and test("^subnet-[0-9a-f]+$"))) and
  (.api_certificate_arn | type == "string" and test("^arn:aws:acm:" + $region + ":" + $account + ":certificate/[A-Za-z0-9-]+$")) and
  (.backend_image | type == "string" and test("^" + $account + "\\.dkr\\.ecr\\." + $region + "\\.amazonaws\\.com/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")) and
  (.backend_hostname | type == "string") and (.frontend_origin | type == "string") and
  (has("SecretString") | not) and (has("SecretBinary") | not)
' "$CAPSULE_PATH" >/dev/null || die "canonical action-values capsule schema or account/region binding is invalid"

if [[ -z "$RUN_ID" ]]; then RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"; fi
[[ "$RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || die "run id has an invalid shape"
if [[ -n "$REPORT_ROOT_OVERRIDE" ]]; then
  REPORT_ROOT="$REPORT_ROOT_OVERRIDE"
else
  REPORT_ROOT="$SCRIPT_ROOT/evidence/eks-deploy/$RUN_ID"
fi
PLAN_PATH="$REPORT_ROOT/create.tfplan"
PLAN_JSON_PATH="$REPORT_ROOT/create-plan.private.json"
PLAN_SHA_PATH="$REPORT_ROOT/create-plan.sha256"
RECEIPT_PATH="$REPORT_ROOT/creation-authorization.private.json"
mkdir -p "$REPORT_ROOT"
chmod 0700 "$REPORT_ROOT"

AWS_ARGS=(--profile "$AWS_PROFILE" --region "$REGION")
ADMIN_ARGS=(--profile "$IAM_ADMIN_PROFILE" --region "$REGION")
ACCOUNT="$(aws "${AWS_ARGS[@]}" sts get-caller-identity --query Account --output text 2>/dev/null)" || die "AWS account preflight failed"
[[ "$ACCOUNT" == "$EXPECTED_ACCOUNT_ID" ]] || die "AWS account does not match the immutable ECR/capsule account"

IAM_POLICY_NAME="kdt-travelplanner-dev-eks-bastion-run-command"
IAM_POLICY_PATH="$REPORT_ROOT/iam-effective-policy.private.json"
IAM_SIMULATION_PATH="$REPORT_ROOT/iam-effective-simulations.private.json"
PROTECTED_STATES_PATH="$REPORT_ROOT/protected-states-before.private.json"
STATE_BUCKET="kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}"
TARGET_KUBERNETES_VERSION=""
TARGET_VERSION_STATUS=""

verify_dev_eks_backend_contract() {
  local backend_file="$TERRAFORM_ROOT/backend.hcl"
  [[ -f "$backend_file" && ! -L "$backend_file" ]] || die "dev-eks backend configuration is missing"
  grep -Eq "^bucket[[:space:]]*=[[:space:]]*\"kdt-travelplanner-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}\"[[:space:]]*$" "$backend_file" || die "dev-eks backend bucket is not exact"
  grep -Eq '^key[[:space:]]*=[[:space:]]*\"dev-eks/terraform.tfstate\"[[:space:]]*$' "$backend_file" || die "dev-eks backend key is not exact"
  grep -Eq "^region[[:space:]]*=[[:space:]]*\"${REGION}\"[[:space:]]*$" "$backend_file" || die "dev-eks backend region is not exact"
}

capture_protected_state_fingerprints() {
  local entries='[]' key label tmp head_err raw_hash shape_hash
  for key in dev/terraform.tfstate dev-runtime/terraform.tfstate dev-load-test/terraform.tfstate; do
    label="${key%/terraform.tfstate}"
    head_err="$(mktemp "${REPORT_ROOT}/state-head.XXXXXX")" || die "protected State probe file could not be created"
    if aws "${AWS_ARGS[@]}" s3api head-object --bucket "$STATE_BUCKET" --key "$key" >/dev/null 2>"$head_err"; then
      tmp="$(mktemp "${REPORT_ROOT}/state-body.XXXXXX")" || { rm -f -- "$head_err"; die "protected State body file could not be created"; }
      aws "${AWS_ARGS[@]}" s3api get-object --bucket "$STATE_BUCKET" --key "$key" "$tmp" >/dev/null 2>>"$head_err" || { rm -f -- "$head_err" "$tmp"; die "protected State read failed"; }
      jq -e 'type == "object"' "$tmp" >/dev/null 2>>"$head_err" || { rm -f -- "$head_err" "$tmp"; die "protected State JSON is invalid"; }
      raw_hash="$(sha256sum "$tmp" | awk '{print $1}')"
      shape_hash="$(jq -cjS '[.resources[]? | {module,type,name,mode,instance_count:(.instances | length)}]' "$tmp" | sha256sum | awk '{print $1}')"
      entries="$(jq -c --arg key "$key" --arg label "$label" --arg raw "$raw_hash" --arg shape "$shape_hash" '. + [{scope:$label,key:$key,status:"present",raw_sha256:$raw,resource_shape_sha256:$shape}]' <<<"$entries")"
      rm -f -- "$tmp"
    else
      if grep -Eqi 'not found|nosuchkey|404' "$head_err"; then
        entries="$(jq -c --arg key "$key" --arg label "$label" '. + [{scope:$label,key:$key,status:"absent"}]' <<<"$entries")"
      else
        rm -f -- "$head_err"
        die "protected State access probe failed"
      fi
    fi
    rm -f -- "$head_err"
  done
  jq -n --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg bucket "$STATE_BUCKET" --arg region "$REGION" --argjson entries "$entries" '{schema_version:"protected-state-fingerprint/v1",captured_at:$captured,bucket:$bucket,region:$region,scopes:$entries}' >"$PROTECTED_STATES_PATH" || die "protected State fingerprint write failed"
  chmod 0600 "$PROTECTED_STATES_PATH"
}

verify_dev_eks_state_empty() {
  local state_output
  if ! state_output="$(AWS_PROFILE="$AWS_PROFILE" terraform -chdir="$TERRAFORM_ROOT" state list 2>"$REPORT_ROOT/dev-eks-state.stderr")"; then
    die "dev-eks State precondition could not be read"
  fi
  [[ -z "$state_output" ]] || die "dev-eks State is not empty; create-only ownership precondition failed"
}

derive_operator_role() {
  local caller role_name
  caller="$(aws "${AWS_ARGS[@]}" sts get-caller-identity --query Arn --output text 2>/dev/null)" || die "operator identity ARN preflight failed"
  [[ "$caller" =~ ^arn:aws:sts::[0-9]{12}:assumed-role/[^/]+/[^/]+$ ]] || die "operator profile must be an assumed SSO role"
  role_name="${caller#*:assumed-role/}"
  role_name="${role_name%%/*}"
  OPERATOR_ROLE_ARN="$(aws "${ADMIN_ARGS[@]}" iam get-role --role-name "$role_name" --query 'Role.Arn' --output text 2>/dev/null)" || die "admin profile could not inspect the operator role"
  [[ "$OPERATOR_ROLE_ARN" =~ ^arn:aws:iam::${EXPECTED_ACCOUNT_ID}:role/.+$ ]] || die "operator role ARN is outside the expected account"
}

load_effective_bastion_policy() {
  local admin_account policy_arn version_id
  admin_account="$(aws "${ADMIN_ARGS[@]}" sts get-caller-identity --query Account --output text 2>/dev/null)" || die "IAM admin account preflight failed"
  [[ "$admin_account" == "$EXPECTED_ACCOUNT_ID" ]] || die "IAM admin profile is outside the expected account"
  policy_arn="$(aws "${ADMIN_ARGS[@]}" iam list-attached-role-policies --role-name "${OPERATOR_ROLE_ARN##*/}" --query "AttachedPolicies[?PolicyName=='$IAM_POLICY_NAME'].PolicyArn | [0]" --output text 2>/dev/null)" || die "dedicated Bastion policy inspection failed"
  [[ "$policy_arn" =~ ^arn:aws:iam::${EXPECTED_ACCOUNT_ID}:policy/.+$ ]] || die "dedicated Bastion Run Command policy is not attached"
  version_id="$(aws "${ADMIN_ARGS[@]}" iam get-policy --policy-arn "$policy_arn" --query 'Policy.DefaultVersionId' --output text 2>/dev/null)" || die "dedicated Bastion policy version lookup failed"
  aws "${ADMIN_ARGS[@]}" iam get-policy-version --policy-arn "$policy_arn" --version-id "$version_id" --query 'PolicyVersion.Document' --output json >"$IAM_POLICY_PATH" 2>/dev/null || die "dedicated Bastion policy document read failed"
  jq -e --arg region "$REGION" --arg account "$EXPECTED_ACCOUNT_ID" '
    def list($value): if ($value | type) == "array" then $value else [$value] end;
    (.Statement | type == "array" and length == 3) and
    (all(.Statement[]; .Effect == "Allow" and (list(.Action) | length == 1))) and
    (any(.Statement[]; list(.Action) == ["ssm:SendCommand"] and list(.Resource) == [("arn:aws:ec2:" + $region + ":" + $account + ":instance/*")] and .Condition == {StringEquals:{"ssm:resourceTag/Environment":"dev", "ssm:resourceTag/Stack":"dev-eks", "ssm:resourceTag/Name":"kdt-travelplanner-dev-eks-bastion"}})) and
    (any(.Statement[]; list(.Action) == ["ssm:SendCommand"] and list(.Resource) == [("arn:aws:ssm:" + $region + "::document/AWS-RunShellScript")] and (has("Condition") | not))) and
    (any(.Statement[]; list(.Action) == ["ssm:GetCommandInvocation"] and list(.Resource) == ["*"] and .Condition == {StringEquals:{"aws:RequestedRegion":$region}}))
  ' "$IAM_POLICY_PATH" >/dev/null || die "dedicated Bastion policy is not the exact least-privilege allowlist"
  chmod 0600 "$IAM_POLICY_PATH"
}

simulate_effective_action() {
  local label="$1" action="$2" resource="$3" simulation
  simulation="$(mktemp "${REPORT_ROOT}/iam-${label}.XXXXXX")" || die "IAM simulation file could not be created"
  case "$label" in
    send-instance)
      aws "${ADMIN_ARGS[@]}" iam simulate-principal-policy --policy-source-arn "$OPERATOR_ROLE_ARN" --action-names "$action" --resource-arns "$resource" \
        --context-entries ContextKeyName=ssm:resourceTag/Environment,ContextKeyValues=dev,ContextKeyType=string ContextKeyName=ssm:resourceTag/Stack,ContextKeyValues=dev-eks,ContextKeyType=string ContextKeyName=ssm:resourceTag/Name,ContextKeyValues=kdt-travelplanner-dev-eks-bastion,ContextKeyType=string \
        --output json >"$simulation" 2>/dev/null || { rm -f -- "$simulation"; die "IAM simulation failed for $label"; } ;;
    *)
      aws "${ADMIN_ARGS[@]}" iam simulate-principal-policy --policy-source-arn "$OPERATOR_ROLE_ARN" --action-names "$action" --resource-arns "$resource" \
        --context-entries ContextKeyName=aws:RequestedRegion,ContextKeyValues="$REGION",ContextKeyType=string --output json >"$simulation" 2>/dev/null || { rm -f -- "$simulation"; die "IAM simulation failed for $label"; } ;;
  esac
  jq -e '.EvaluationResults | length == 1 and .[0].EvalDecision == "allowed"' "$simulation" >/dev/null || { rm -f -- "$simulation"; die "IAM simulation denied $label"; }
  jq -c --arg label "$label" --arg action "$action" --arg resource "$resource" '{label:$label,action:$action,resource:$resource,decision:.EvaluationResults[0].EvalDecision,matched_statements:.EvaluationResults[0].MatchedStatements}' "$simulation"
  rm -f -- "$simulation"
}

run_iam_and_provenance_preflight() {
  local image_repo image_digest repository_name ecr_digest
  image_repo="${BACKEND_IMAGE%@*}"
  image_digest="${BACKEND_IMAGE##*@}"
  repository_name="${image_repo#*/}"
  derive_operator_role
  load_effective_bastion_policy
  {
    simulate_effective_action send-instance ssm:SendCommand "arn:aws:ec2:${REGION}:${EXPECTED_ACCOUNT_ID}:instance/i-00000000000000001"
    simulate_effective_action send-document ssm:SendCommand "arn:aws:ssm:${REGION}::document/AWS-RunShellScript"
    simulate_effective_action get-invocation ssm:GetCommandInvocation '*'
    simulate_effective_action ecr-describe ecr:DescribeImages "arn:aws:ecr:${REGION}:${EXPECTED_ACCOUNT_ID}:repository/${repository_name}"
  } | jq -s --arg captured "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg operator "$OPERATOR_ROLE_ARN" --arg admin "$IAM_ADMIN_PROFILE" '{schema_version:"iam-effective-proof/v1",captured_at:$captured,operator_role_arn:$operator,admin_profile:$admin,simulations:.}' >"$IAM_SIMULATION_PATH" || die "IAM simulation proof write failed"
  chmod 0600 "$IAM_SIMULATION_PATH"
  ecr_digest="$(aws "${AWS_ARGS[@]}" ecr describe-images --repository-name "$repository_name" --registry-id "$EXPECTED_ACCOUNT_ID" --image-ids "imageDigest=$image_digest" --query 'imageDetails[0].imageDigest' --output text 2>/dev/null)" || die "Backend image digest could not be verified in ECR before Terraform apply"
  [[ "$ecr_digest" == "$image_digest" ]] || die "Backend image digest is not present in ECR before Terraform apply"
  capture_protected_state_fingerprints
}

create_and_validate_plan() {
  if [[ "$MODE" == "plan" ]]; then
    [[ ! -e "$PLAN_PATH" ]] || die "fresh plan report root already contains a create plan; use a new run id"
    AWS_PROFILE="$AWS_PROFILE" terraform -chdir="$TERRAFORM_ROOT" plan -input=false -out="$PLAN_PATH" >"$REPORT_ROOT/terraform-plan.log" 2>&1 || die "Terraform create plan failed"
  else
    [[ -f "$PLAN_PATH" && ! -L "$PLAN_PATH" ]] || die "approved create plan is missing; run plan mode first"
  fi
  chmod 0400 "$PLAN_PATH"
  PLAN_SHA256="$(sha256sum "$PLAN_PATH" | awk '{print $1}')"
  AWS_PROFILE="$AWS_PROFILE" terraform -chdir="$TERRAFORM_ROOT" show -json "$PLAN_PATH" >"$PLAN_JSON_PATH" 2>"$REPORT_ROOT/terraform-show.log" || die "Terraform create plan could not be decoded"
  chmod 0600 "$PLAN_JSON_PATH"
  jq -e '[.resource_changes[]?.change.actions[]? | select(. == "delete" or . == "replace")] | length == 0' "$PLAN_JSON_PATH" >/dev/null || die "create plan contains delete or replace"
  jq -e '([.. | objects | select(has("endpoint_public_access")) | .endpoint_public_access] | index(true) == null)' "$PLAN_JSON_PATH" >/dev/null || die "create plan enables public EKS endpoint access"
  jq -e '.variables.kubernetes_version.value | type == "string" and test("^1\\.[0-9]{2}$")' "$PLAN_JSON_PATH" >/dev/null || die "create plan has no valid EKS minor"
  jq -e '[.resource_changes[]?.address | select(test("(^|\\.)dev-runtime|dev-load-test|dev/terraform\\.tfstate"))] | length == 0' "$PLAN_JSON_PATH" >/dev/null || die "create plan touches a protected State scope"
  TARGET_KUBERNETES_VERSION="$(jq -er '.variables.kubernetes_version.value | select(type == "string" and test("^1\\.[0-9]{2}$"))' "$PLAN_JSON_PATH")" || die "create plan Kubernetes version is missing"
  local support_json support_count
  support_json="$(aws "${AWS_ARGS[@]}" eks describe-cluster-versions --cluster-type eks --cluster-versions "$TARGET_KUBERNETES_VERSION" --no-paginate --output json 2>/dev/null)" || die "EKS support metadata lookup failed before approval"
  support_count="$(jq -er '.clusterVersions | length' <<<"$support_json")" || die "EKS support metadata response is invalid"
  [[ "$support_count" == "1" ]] || die "EKS support metadata result cardinality is invalid before approval"
  TARGET_VERSION_STATUS="$(jq -er '.clusterVersions[0] | select(.clusterVersion == $version and .clusterType == "eks") | .versionStatus' --arg version "$TARGET_KUBERNETES_VERSION" <<<"$support_json")" || die "EKS support metadata target is invalid before approval"
  [[ "$TARGET_VERSION_STATUS" == "STANDARD_SUPPORT" ]] || die "EKS target $TARGET_KUBERNETES_VERSION is not STANDARD_SUPPORT before approval"
  printf '%s\n' "$PLAN_SHA256" >"$PLAN_SHA_PATH"
  chmod 0600 "$PLAN_SHA_PATH"

  if [[ ! -f "$RECEIPT_PATH" || -L "$RECEIPT_PATH" ]]; then
    jq -n --arg run "$RUN_ID" --arg account "$EXPECTED_ACCOUNT_ID" --arg region "$REGION" --arg plan "$PLAN_SHA256" --arg backend_config "$BACKEND_CONFIG_SHA256" --arg capsule "$CAPSULE_SHA256" --arg image "$BACKEND_IMAGE" --arg hostname "$BACKEND_HOSTNAME" --arg frontend "$FRONTEND_ORIGIN" --arg plan_id "$PLAN_ID" --argjson plan_version "$PLAN_VERSION" --arg manifest_sha "$PLAN_MANIFEST_SHA256" --arg manifest_path "$PLAN_MANIFEST_REALPATH" --arg handoff_path "$PLAN_HANDOFF_REALPATH" --arg handoff_sha "$PLAN_HANDOFF_SHA256" '{
      schema_version:"dev-eks-create-authorization/v1",
      plan_id:$plan_id, plan_version:$plan_version,
      handoff_schema_version:"plan-handoff/v1", handoff_path:$handoff_path, handoff_sha256:$handoff_sha,
      manifest_schema_version:"plan-manifest/v3", manifest_path:$manifest_path, manifest_sha256:$manifest_sha,
      run_id:$run, issued_at:(now|todateiso8601), expires_at:((now+7200)|todateiso8601),
      status:"active", single_use:true, expected_account_id:$account, expected_region:$region,
      terraform_backend_key:"dev-eks/terraform.tfstate", terraform_backend_config_sha256:$backend_config, terraform_plan_sha256:$plan,
      input_capsule_path:$capsule_path, input_capsule_sha256:$capsule,
      kubernetes_version:$kubernetes_version, kubernetes_version_status:$kubernetes_version_status,
      backend_image:$image, backend_hostname:$hostname, frontend_origin:$frontend,
      bundle_revision_sha256:null, runtime_values_sha256:null, render_sha256:null,
      protected_backends:["dev/terraform.tfstate","dev-runtime/terraform.tfstate","dev-load-test/terraform.tfstate"],
      protected_resources:["persistent VPC and subnets","ACM certificates","ECR repositories and images","profile image storage","application Secrets Manager","external DNS provider"],
      permitted_actions:["apply exact create/update-only dev-eks Terraform plan","run exact staged Kubernetes deployment through tagged private Bastion","run bounded ALB/HTTPS/observability smoke","retain created dev-eks resources"],
      forbidden_actions:["terraform destroy","Kubernetes delete","replace or import","Cloudflare mutation","protected State mutation"],
      paid_approval:{status:"pending", action:("APPLY DEV-EKS CREATE-AND-RETAIN "+$plan), plan_sha256:$plan}
    }' --arg capsule_path "$CAPSULE_REALPATH" --arg kubernetes_version "$TARGET_KUBERNETES_VERSION" --arg kubernetes_version_status "$TARGET_VERSION_STATUS" >"$RECEIPT_PATH"
    chmod 0600 "$RECEIPT_PATH"
  else
    jq -e --arg run "$RUN_ID" --arg plan "$PLAN_SHA256" --arg backend_config "$BACKEND_CONFIG_SHA256" --arg plan_id "$PLAN_ID" --argjson plan_version "$PLAN_VERSION" --arg manifest_sha "$PLAN_MANIFEST_SHA256" --arg manifest_path "$PLAN_MANIFEST_REALPATH" --arg handoff_path "$PLAN_HANDOFF_REALPATH" --arg handoff_sha "$PLAN_HANDOFF_SHA256" '.schema_version == "dev-eks-create-authorization/v1" and .run_id == $run and .plan_id == $plan_id and .plan_version == $plan_version and .manifest_sha256 == $manifest_sha and .manifest_path == $manifest_path and .handoff_path == $handoff_path and .handoff_sha256 == $handoff_sha and .terraform_backend_config_sha256 == $backend_config and .terraform_plan_sha256 == $plan and .status == "active" and .paid_approval.status == "pending"' "$RECEIPT_PATH" >/dev/null || die "existing create receipt does not match this v9 handoff or plan"
  fi
}

verify_dev_eks_backend_contract
verify_dev_eks_state_empty
run_iam_and_provenance_preflight
create_and_validate_plan
EXPECTED_APPROVAL="APPLY DEV-EKS CREATE-AND-RETAIN $PLAN_SHA256"
if [[ "$MODE" == "plan" || -z "$APPROVAL" ]]; then
  printf 'status=waiting_approval run_id=%s plan_sha256=%s\n' "$RUN_ID" "$PLAN_SHA256" >&2
  printf 'Type exactly: %s\n' "$EXPECTED_APPROVAL" >&2
  exit 20
fi
[[ "$APPROVAL" == "$EXPECTED_APPROVAL" ]] || die "exact paid create approval does not match this plan"

approved="$(mktemp "${RECEIPT_PATH}.approved.XXXXXX")"
jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg action "$EXPECTED_APPROVAL" --arg plan "$PLAN_SHA256" '.paid_approval.status="approved" | .paid_approval.approved_at=$now | .paid_approval.action=$action | .paid_approval.plan_sha256=$plan' "$RECEIPT_PATH" >"$approved" || { rm -f -- "$approved"; die "paid approval receipt update failed"; }
chmod 0600 "$approved"
mv -f -- "$approved" "$RECEIPT_PATH"

exec bash "$SCRIPT_ROOT/scripts/eks/deploy-dev-eks.sh" \
  --mode run --non-interactive --run-id "$RUN_ID" \
  --aws-profile "$AWS_PROFILE" --region "$REGION" --expected-account-id "$EXPECTED_ACCOUNT_ID" \
  --terraform-plan "$PLAN_PATH" --terraform-plan-sha256 "$PLAN_SHA256" \
  --backend-image "$BACKEND_IMAGE" --backend-hostname "$BACKEND_HOSTNAME" \
  --frontend-origin "$FRONTEND_ORIGIN" --action-values-capsule "$CAPSULE_PATH" \
  --plan-handoff "$PLAN_HANDOFF_REALPATH" \
  --authorization-receipt "$RECEIPT_PATH"
