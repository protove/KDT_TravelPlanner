#!/usr/bin/env bash
# Orchestrate an AWS B-01 execution end to end, per
# aws-load-test-handoff/plans/03_AWS_B01_EXECUTION_PLAN.md and the team-lead
# TEAM_MEMBER_B01_ACTION_REQUEST.md §4.2 "B-01 실행 순서":
#
#   target -> seed -> smoke -> ramp -> [operator picks a candidate rate] ->
#   baseline x3 (same rate) -> D-005 arrival-rate record -> spike/soak/scale-step ->
#   evidence (Grafana Annotation + Query; CloudWatch is collected in
#   target_stage's aws/ dir; PNG excluded for now — see D-003/Plan04) ->
#   cleanup -> cleanup-result record -> provisional evidence review ->
#   [operator approves D-006 freeze] -> freeze metadata -> final export
#   (safety scan + checksum manifest + S3 upload, gated on freeze metadata
#   existing) -> ephemeral resource teardown (out of scope: separate
#   `terraform destroy`, see scripts/loadtest/aws/check-destroy-gate.sh)
#
# This script only parses flags and resolves the AWS target once; it then
# delegates one phase at a time to run-aws-b01.sh, exporting the resolved
# env vars every phase needs (mirrors run-compose-rehearsal.sh's
# export-then-delegate structure). seed-aws-load-data.py, cleanup-aws-load-data.py,
# and upload-aws-evidence.py are consumed as-is — this script does not
# reimplement any of their logic.
#
# Two decisions in this sequence require a human, not this script, and each
# one pauses `all` and asks for a second invocation with the decision as a
# flag:
#   - D-005 (the normal arrival-rate): only settable after a human reviews
#     this run's Ramp output (see decisions/OPEN_DECISIONS.md). `all` runs
#     through Ramp and stops unless --confirmed-rate is already supplied.
#   - D-006 (SLO freeze): only settable after a human reviews this run's
#     full provisional evidence (all phases + cleanup-result). `all` runs
#     through the provisional-review stage and stops unless
#     --slo-freeze-approved-by is already supplied. Final export (the S3
#     upload) refuses to run at all until freeze-metadata.json exists —
#     this is what keeps "final export happens after freeze" true even if
#     someone invokes `export` standalone instead of via `all`.
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MODE="all"
PROFILE="$REPOSITORY_ROOT/load-tests/aws/profiles/ec2-b01.json"
SLO_CONTRACT="$REPOSITORY_ROOT/load-tests/aws/contracts/slo-v1.0.json"
SLO_CONTRACT_EXPLICIT=0
TARGET_PLATFORM="ec2"
REGION=""
ENVIRONMENT=""
EXPECTED_ACCOUNT_ID=""
ALB_ARN=""
RUNNER_ID=""
RUNNER_INSTANCE_TYPE="t3.small"
BASE_URL=""
S3_BUCKET=""
S3_PREFIX="evidence/aws-load-tests"
DRY_RUN=0
MAX_RATE=""
MAX_VUS=""
RUN_ID=""
K6_IMAGE=""
CONFIRMED_RATE=""
USERS=80
DATABASE_HOST=""
DATABASE_PORT=5432
DATABASE_NAME=""
DATABASE_SECRET_ARN=""
DB_INSTANCE_IDENTIFIER=""
REDIS_HOST=""
REDIS_PORT=6379
REDIS_IAM_USER=""
REDIS_REPLICATION_GROUP_ID=""
CACHE_CLUSTER_ID=""
GRAFANA_URL="${GRAFANA_URL:-}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-}"
PROMETHEUS_URL=""
SLO_FREEZE_APPROVED_BY=""
EKS_CLUSTER_NAME="kdt-travelplanner-dev-eks"
EKS_NODE_GROUP_NAME="kdt-travelplanner-dev-eks-nodes"
EKS_BASTION_ID=""
BACKEND_NAMESPACE="travel-planner"
BACKEND_DEPLOYMENT="backend"
PROFILE_SHA256=""
SOURCE_COMMIT_SHA=""
START_RATE="${START_RATE:-}"
DURATION="${DURATION:-}"
WARMUP="${WARMUP:-}"
RAMP_PREALLOCATED_VUS="${RAMP_PREALLOCATED_VUS:-}"
RAMP_MAX_VUS="${RAMP_MAX_VUS:-}"
BASELINE_PREALLOCATED_VUS="${BASELINE_PREALLOCATED_VUS:-}"
BASELINE_MAX_VUS="${BASELINE_MAX_VUS:-}"
SPIKE_PREALLOCATED_VUS="${SPIKE_PREALLOCATED_VUS:-}"
SPIKE_MAX_VUS="${SPIKE_MAX_VUS:-}"
SPIKE_PEAK_MULTIPLIER="${SPIKE_PEAK_MULTIPLIER:-}"
SPIKE_HOLD="${SPIKE_HOLD:-}"
SOAK_PREALLOCATED_VUS="${SOAK_PREALLOCATED_VUS:-}"
SOAK_MAX_VUS="${SOAK_MAX_VUS:-}"
SCALE_STEP_PREALLOCATED_VUS="${SCALE_STEP_PREALLOCATED_VUS:-}"
SCALE_STEP_MAX_VUS="${SCALE_STEP_MAX_VUS:-}"
CAPACITY_STRESS_PREALLOCATED_VUS="${CAPACITY_STRESS_PREALLOCATED_VUS:-100}"
CAPACITY_STRESS_MAX_VUS="${CAPACITY_STRESS_MAX_VUS:-320}"

usage() {
  cat <<'USAGE'
usage: orchestrate-aws-b01.sh [target|seed|smoke|ramp|baseline|d005-record|spike|soak|scale-step|capacity-stress|evidence|cleanup|provisional-review|freeze|export|all] [options]

Required:
  --profile PATH                 AWS load-test profile JSON (default: load-tests/aws/profiles/ec2-b01.json)
  --slo-contract PATH            versioned SLO contract (comparison default: v1.1 candidate)
  --target-platform PLATFORM     Explicit target adapter: ec2 or eks (default: ec2)
  --region REGION
  --environment ENVIRONMENT
  --expected-account-id ID       12-digit AWS account ID this run is approved to target
  --alb-arn ARN                  Exact ALB ARN to verify and resolve BASE_URL from
  --base-url URL                 Approved custom HTTPS hostname (never the ALB *.amazonaws.com DNS name)
  --runner-id INSTANCE_ID        Standalone Runner EC2 instance ID (must be running and SSM Online)
  --runner-instance-type TYPE    Expected Runner type (default: t3.small)
  --s3-prefix PREFIX             Default: evidence/aws-load-tests
  --dry-run                      Skip real aws/docker calls; print the planned actions
  --max-rate RATE                Operator ceiling on top of profile.limits.maxRate
  --max-vus VUS                  Operator ceiling on top of profile.limits.maxVUs

Also required for most modes:
  --s3-bucket NAME                (seed/export/all) evidence S3 bucket
  --k6-image DIGEST                (smoke/ramp/baseline/spike/soak/scale-step/capacity-stress/all) digest-pinned k6 image
  --database-host/--database-name/--database-secret-arn   (seed/cleanup/all)
                                    --database-secret-arn must be a dedicated test-only Secret,
                                    JSON {"username":..,"password":..} (never the RDS master secret)
  --db-instance-identifier ID     CloudWatch RDS dimension for local Grafana export (optional at Runner time)
  --redis-host/--redis-iam-user/--redis-replication-group-id
                                    (seed/cleanup/all; omit all three together to skip Redis in cleanup —
                                    seed always requires Redis). ElastiCache RBAC + IAM auth, never a Secret.
  --cache-cluster-id ID            CloudWatch ElastiCache dimension for local Grafana export
  --confirmed-rate RATE            (baseline/spike/all after Ramp) D-005 operator-confirmed arrival-rate
  --slo-freeze-approved-by NAME    (freeze/all after provisional-review) D-006 approver identity (person or role, not a secret)

Optional:
  --run-id ID                     Default: aws-b01-<UTC timestamp>
  --users N                       Default: 80 (Spike maxVUs; one credential per AWS VU)
  --database-port PORT            Default: 5432
  --redis-port PORT               Default: 6379
  --grafana-url / --grafana-user / --grafana-password   (evidence/all) skip annotation publish if omitted
  --prometheus-url URL            (evidence/all) skip Query JSON collection if omitted

EKS target options (required when --target-platform eks):
  --eks-cluster-name NAME        Expected EKS cluster (default: kdt-travelplanner-dev-eks)
  --eks-node-group-name NAME     Expected managed node group (default: kdt-travelplanner-dev-eks-nodes)
  --eks-bastion-id INSTANCE_ID   SSM-only bastion used for kubectl evidence
  --backend-namespace NAME       Backend namespace (default: travel-planner)
  --backend-deployment NAME      Backend Deployment (default: backend)

Modes:
  target|seed|smoke|ramp|baseline|spike|soak|scale-step|capacity-stress   individual phases with target validation
  evidence            Grafana Annotation + Query collection (post-Spike; PNG excluded, see D-003/Plan04)
  cleanup              synthetic data cleanup; writes cleanup-result.json into the evidence bundle
  provisional-review    writes provisional-review.json (an inventory, not a pass/fail verdict) for the
                        operator to read before approving D-006
  freeze                writes freeze-metadata.json (D-006); requires provisional-review.json to exist and
                        --slo-freeze-approved-by
  export                final safety scan + checksum manifest + S3 upload; refuses to run unless
                        freeze-metadata.json exists in the evidence root
  all                    runs the full sequence, pausing at the two operator-decision points above
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    target|seed|smoke|ramp|baseline|d005-record|spike|soak|scale-step|capacity-stress|evidence|cleanup|provisional-review|freeze|export|all) MODE="$1"; shift ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --slo-contract) SLO_CONTRACT="$2"; SLO_CONTRACT_EXPLICIT=1; shift 2 ;;
    --target-platform) TARGET_PLATFORM="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="$2"; shift 2 ;;
    --alb-arn) ALB_ARN="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --runner-id) RUNNER_ID="$2"; shift 2 ;;
    --runner-instance-type) RUNNER_INSTANCE_TYPE="$2"; shift 2 ;;
    --s3-bucket) S3_BUCKET="$2"; shift 2 ;;
    --s3-prefix) S3_PREFIX="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --max-rate) MAX_RATE="$2"; shift 2 ;;
    --max-vus) MAX_VUS="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --k6-image) K6_IMAGE="$2"; shift 2 ;;
    --confirmed-rate) CONFIRMED_RATE="$2"; shift 2 ;;
    --users) USERS="$2"; shift 2 ;;
    --database-host) DATABASE_HOST="$2"; shift 2 ;;
    --database-port) DATABASE_PORT="$2"; shift 2 ;;
    --database-name) DATABASE_NAME="$2"; shift 2 ;;
    --database-secret-arn) DATABASE_SECRET_ARN="$2"; shift 2 ;;
    --db-instance-identifier) DB_INSTANCE_IDENTIFIER="$2"; shift 2 ;;
    --redis-host) REDIS_HOST="$2"; shift 2 ;;
    --redis-port) REDIS_PORT="$2"; shift 2 ;;
    --redis-iam-user) REDIS_IAM_USER="$2"; shift 2 ;;
    --redis-replication-group-id) REDIS_REPLICATION_GROUP_ID="$2"; shift 2 ;;
    --cache-cluster-id) CACHE_CLUSTER_ID="$2"; shift 2 ;;
    --grafana-url) GRAFANA_URL="$2"; shift 2 ;;
    --grafana-user) GRAFANA_ADMIN_USER="$2"; shift 2 ;;
    --grafana-password) GRAFANA_ADMIN_PASSWORD="$2"; shift 2 ;;
    --prometheus-url) PROMETHEUS_URL="$2"; shift 2 ;;
    --slo-freeze-approved-by) SLO_FREEZE_APPROVED_BY="$2"; shift 2 ;;
    --eks-cluster-name) EKS_CLUSTER_NAME="$2"; shift 2 ;;
    --eks-node-group-name) EKS_NODE_GROUP_NAME="$2"; shift 2 ;;
    --eks-bastion-id) EKS_BASTION_ID="$2"; shift 2 ;;
    --backend-namespace) BACKEND_NAMESPACE="$2"; shift 2 ;;
    --backend-deployment) BACKEND_DEPLOYMENT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$TARGET_PLATFORM" in
  ec2|eks) ;;
  *) echo "--target-platform must be ec2 or eks" >&2; exit 2 ;;
esac

COMPARISON_PROFILE=0
if [[ "$PROFILE" == *ec2-eks-comparison-v1.1.json* || "$SLO_CONTRACT" == *slo-v1.1-* ]]; then
  COMPARISON_PROFILE=1
fi
if [[ "$COMPARISON_PROFILE" == "1" && "$SLO_CONTRACT_EXPLICIT" == "0" ]]; then
  SLO_CONTRACT="$REPOSITORY_ROOT/load-tests/aws/contracts/slo-v1.1-candidate.json"
fi
if [[ "$COMPARISON_PROFILE" == "1" && "$MODE" == "all" ]]; then
  echo "comparison profile forbids 'all': evidence capture, human recovery, rollback, freeze/export and cleanup remain operator-directed phases" >&2
  exit 2
fi

for required in REGION ENVIRONMENT EXPECTED_ACCOUNT_ID ALB_ARN BASE_URL RUNNER_ID MAX_RATE MAX_VUS; do
  if [[ -z "${!required}" ]]; then
    echo "--${required,,} is required" >&2
    exit 2
  fi
done
if [[ ! "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "--expected-account-id must be exactly 12 digits" >&2
  exit 2
fi
if [[ ! "$BASE_URL" =~ ^https://[^/]+$ || "$BASE_URL" == *amazonaws.com* ]]; then
  echo "--base-url must be an approved custom HTTPS hostname, not an AWS ALB DNS name" >&2
  exit 2
fi
if [[ ! "$RUNNER_INSTANCE_TYPE" =~ ^t3\.[a-z0-9]+$ ]]; then
  echo "--runner-instance-type must be a t3 family instance type" >&2
  exit 2
fi
if [[ "$TARGET_PLATFORM" == "eks" ]]; then
  for required in EKS_CLUSTER_NAME EKS_NODE_GROUP_NAME EKS_BASTION_ID BACKEND_NAMESPACE BACKEND_DEPLOYMENT; do
    if [[ -z "${!required}" ]]; then
      echo "--${required,,} is required for --target-platform eks" >&2
      exit 2
    fi
  done
  for identifier in "$EKS_CLUSTER_NAME" "$EKS_NODE_GROUP_NAME" "$BACKEND_NAMESPACE" "$BACKEND_DEPLOYMENT"; do
    if [[ ! "$identifier" =~ ^[A-Za-z0-9._-]+$ ]]; then
      echo "EKS names must contain only letters, digits, dot, underscore or hyphen" >&2
      exit 2
    fi
  done
  if [[ ! "$EKS_BASTION_ID" =~ ^i-[0-9a-f]{8,32}$ ]]; then
    echo "--eks-bastion-id must be an EC2 instance ID" >&2
    exit 2
  fi
fi
if [[ ! -f "$PROFILE" ]]; then
  echo "--profile file does not exist: $PROFILE" >&2
  exit 2
fi
if [[ ! -f "$SLO_CONTRACT" ]]; then
  echo "--slo-contract file does not exist: $SLO_CONTRACT" >&2
  exit 2
fi
python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/validate-aws-profile.py" "$PROFILE"

RUN_ID="${RUN_ID:-aws-b01-$(date -u +%Y%m%d-%H%M%S)}"
# Tests and diagnostics may relocate evidence with B01_EVIDENCE_BASE so the
# repository's protected evidence tree is never written by a test run.
EVIDENCE_BASE="${B01_EVIDENCE_BASE:-$REPOSITORY_ROOT/evidence/aws-load-tests}"
EVIDENCE_ROOT="$EVIDENCE_BASE/$RUN_ID"
DATA_FILE="$EVIDENCE_ROOT/data.json"
FIXTURES_DIR="$EVIDENCE_ROOT/fixtures"
PROFILE_SHA256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$PROFILE")"
SLO_CONTRACT_SHA256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$SLO_CONTRACT")"
SOURCE_COMMIT_SHA="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
mkdir -p "$EVIDENCE_ROOT"

AWS_CMD=(aws)
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[b01] --dry-run: no aws/docker commands will be executed"
fi

run_aws_json() {
  # Runs an `aws ... --output json` command unless --dry-run, in which case
  # it prints the command and returns an empty JSON object so downstream
  # `python3 -c 'json.load(...)'` calls still have valid input to parse.
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] aws $*" >&2
    echo '{}'
    return 0
  fi
  aws "$@"
}

STAGE_DIR="$EVIDENCE_ROOT/stages"
stage_confirmed_rate() {
  local stage="$1"
  case "$stage" in
    baseline-*|d005|spike|soak|scale-step|capacity-stress) printf '%s' "${CONFIRMED_RATE:-}" ;;
    *) printf '' ;;
  esac
}

stage_input_digest() {
  local stage="$1"
  python3 - "$stage" "$RUN_ID" "$PROFILE_SHA256" "${SLO_CONTRACT_SHA256:-}" "$SOURCE_COMMIT_SHA" \
    "${TARGET_PLATFORM:-ec2}" "${EKS_CLUSTER_NAME:-}" "${EKS_NODE_GROUP_NAME:-}" "${EKS_BASTION_ID:-}" \
    "${BACKEND_NAMESPACE:-}" "${BACKEND_DEPLOYMENT:-}" \
    "$REGION" "$ENVIRONMENT" "$EXPECTED_ACCOUNT_ID" "$ALB_ARN" "$BASE_URL" \
    "$RUNNER_ID" "$RUNNER_INSTANCE_TYPE" "$MAX_RATE" "$MAX_VUS" "$K6_IMAGE" "$USERS" \
    "$DATABASE_HOST" "$DATABASE_PORT" "$DATABASE_NAME" "$DATABASE_SECRET_ARN" \
    "$DB_INSTANCE_IDENTIFIER" "$REDIS_HOST" "$REDIS_PORT" "$REDIS_IAM_USER" \
    "$REDIS_REPLICATION_GROUP_ID" "$CACHE_CLUSTER_ID" "$S3_BUCKET" "$S3_PREFIX" \
    "$GRAFANA_URL" "$GRAFANA_ADMIN_USER" "$GRAFANA_ADMIN_PASSWORD" "$PROMETHEUS_URL" \
    "$SLO_FREEZE_APPROVED_BY" "$START_RATE" "$DURATION" "$WARMUP" \
    "$RAMP_PREALLOCATED_VUS" "$RAMP_MAX_VUS" "$BASELINE_PREALLOCATED_VUS" "$BASELINE_MAX_VUS" \
    "$SPIKE_PREALLOCATED_VUS" "$SPIKE_MAX_VUS" "$SPIKE_PEAK_MULTIPLIER" "$SPIKE_HOLD" \
    "${SOAK_PREALLOCATED_VUS:-}" "${SOAK_MAX_VUS:-}" "${SCALE_STEP_PREALLOCATED_VUS:-}" "${SCALE_STEP_MAX_VUS:-}" \
    "${CAPACITY_STRESS_PREALLOCATED_VUS:-}" "${CAPACITY_STRESS_MAX_VUS:-}" \
    "$(stage_confirmed_rate "$stage")" <<'PY'
import hashlib
import json
import sys

(
    stage, run_id, profile_sha, slo_contract_sha, source_commit_sha,
    target_platform, eks_cluster_name, eks_node_group_name, eks_bastion_id,
    backend_namespace, backend_deployment,
    region, environment, expected_account_id, alb_arn, base_url,
    runner_id, runner_instance_type, max_rate, max_vus, k6_image, users,
    database_host, database_port, database_name, database_secret_arn,
    db_instance_identifier, redis_host, redis_port, redis_iam_user,
    redis_replication_group_id, cache_cluster_id, s3_bucket, s3_prefix,
    grafana_url, grafana_user, grafana_password, prometheus_url,
    slo_freeze_approved_by, start_rate, duration, warmup,
    ramp_preallocated_vus, ramp_max_vus, baseline_preallocated_vus, baseline_max_vus,
    spike_preallocated_vus, spike_max_vus, spike_peak_multiplier, spike_hold,
    soak_preallocated_vus, soak_max_vus, scale_step_preallocated_vus, scale_step_max_vus,
    capacity_stress_preallocated_vus, capacity_stress_max_vus,
    confirmed_rate,
) = sys.argv[1:]

common = {
    "targetPlatform": target_platform,
    "region": region,
    "environment": environment,
    "expectedAccountId": expected_account_id,
    "albArn": alb_arn,
    "baseUrl": base_url,
    "runnerId": runner_id,
    "runnerInstanceType": runner_instance_type,
    "maxRate": max_rate,
    "maxVus": max_vus,
}
if target_platform == "eks":
    common["eks"] = {
        "clusterName": eks_cluster_name,
        "nodeGroupName": eks_node_group_name,
        "bastionId": eks_bastion_id,
        "backendNamespace": backend_namespace,
        "backendDeployment": backend_deployment,
    }
payload = {
    "stage": stage,
    "runId": run_id,
    "profileSha256": profile_sha,
    "sloContractSha256": slo_contract_sha,
    "sourceCommitSha": source_commit_sha,
    **common,
}

if stage == "target":
    payload.update({
        "dbInstanceIdentifier": db_instance_identifier,
        "cacheClusterId": cache_cluster_id,
    })
elif stage == "seed":
    payload.update({
        "users": users,
        "s3Bucket": s3_bucket,
        "databaseHost": database_host,
        "databasePort": database_port,
        "databaseName": database_name,
        "databaseSecretArn": database_secret_arn,
        "redisHost": redis_host,
        "redisPort": redis_port,
        "redisIamUser": redis_iam_user,
        "redisReplicationGroupId": redis_replication_group_id,
    })
elif stage in {"smoke", "ramp", "spike", "soak", "scale-step", "capacity-stress"} or stage.startswith("baseline-"):
    payload["k6Image"] = k6_image
    payload["credentialLifecycle"] = {
        "users": users,
        "databaseHost": database_host,
        "databasePort": database_port,
        "databaseName": database_name,
        "databaseSecretArn": database_secret_arn,
        "redisHost": redis_host,
        "redisPort": redis_port,
        "redisIamUser": redis_iam_user,
        "redisReplicationGroupId": redis_replication_group_id,
    }
    if stage == "ramp":
        payload["effectiveK6Overrides"] = {
            "startRate": start_rate,
            "preAllocatedVUs": ramp_preallocated_vus,
            "maxVUs": ramp_max_vus,
        }
    elif stage.startswith("baseline-"):
        payload["effectiveK6Overrides"] = {
            "warmup": warmup,
            "duration": duration,
            "preAllocatedVUs": baseline_preallocated_vus,
            "maxVUs": baseline_max_vus,
        }
    elif stage == "spike":
        payload["effectiveK6Overrides"] = {
            "preAllocatedVUs": spike_preallocated_vus,
            "maxVUs": spike_max_vus,
            "peakMultiplier": spike_peak_multiplier,
            "hold": spike_hold,
        }
    elif stage == "soak":
        payload["effectiveK6Overrides"] = {
            "rate": confirmed_rate,
            "preAllocatedVUs": soak_preallocated_vus,
            "maxVUs": soak_max_vus,
        }
    elif stage == "scale-step":
        payload["effectiveK6Overrides"] = {
            "rate": confirmed_rate,
            "preAllocatedVUs": scale_step_preallocated_vus,
            "maxVUs": scale_step_max_vus,
        }
    elif stage == "capacity-stress":
        payload["effectiveK6Overrides"] = {
            "rate": confirmed_rate,
            "preAllocatedVUs": capacity_stress_preallocated_vus,
            "maxVUs": capacity_stress_max_vus,
            "stageMultipliers": [1, 2, 4, 8],
        }
    if stage in {"spike", "soak", "scale-step", "capacity-stress"} or stage.startswith("baseline-"):
        payload["confirmedRate"] = confirmed_rate
elif stage == "d005":
    payload["confirmedRate"] = confirmed_rate
elif stage == "evidence":
    payload.update({
        "grafanaUrl": grafana_url,
        "grafanaUser": grafana_user,
        # Store only a fingerprint; the Grafana password never enters the
        # marker or digest output as a raw value.
        "grafanaPasswordSha256": hashlib.sha256(grafana_password.encode()).hexdigest(),
        "prometheusUrl": prometheus_url,
    })
elif stage == "cleanup":
    payload.update({
        "databaseHost": database_host,
        "databasePort": database_port,
        "databaseName": database_name,
        "databaseSecretArn": database_secret_arn,
        "redisHost": redis_host,
        "redisPort": redis_port,
        "redisIamUser": redis_iam_user,
        "redisReplicationGroupId": redis_replication_group_id,
    })
elif stage == "freeze":
    payload["sloFreezeApprovedBy"] = slo_freeze_approved_by
elif stage == "export":
    payload.update({"s3Bucket": s3_bucket, "s3Prefix": s3_prefix})

canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
PY
}

stage_is_complete() {
  local stage="$1"
  local marker="$STAGE_DIR/$stage.json"
  [[ "$DRY_RUN" == "1" ]] && return 1
  [[ -f "$marker" ]] || return 1
  local stage_rate stage_digest
  stage_rate="$(stage_confirmed_rate "$stage")"
  stage_digest="$(stage_input_digest "$stage")"
  python3 - "$marker" "$RUN_ID" "$PROFILE_SHA256" "$stage_rate" "$stage_digest" <<'PY'
import json
import sys
from pathlib import Path

marker, run_id, profile_sha, confirmed_rate, input_digest = sys.argv[1:]
payload = json.loads(Path(marker).read_text(encoding="utf-8"))
if payload.get("runId") != run_id or payload.get("profileSha256") != profile_sha:
    raise SystemExit(1)
if (payload.get("confirmedRate") or "") != confirmed_rate:
    raise SystemExit(1)
if payload.get("inputDigest") != input_digest:
    raise SystemExit(1)
PY
}

mark_stage_complete() {
  local stage="$1"
  [[ "$DRY_RUN" == "1" ]] && return 0
  mkdir -p "$STAGE_DIR"
  local stage_rate stage_digest
  stage_rate="$(stage_confirmed_rate "$stage")"
  stage_digest="$(stage_input_digest "$stage")"
  python3 - "$STAGE_DIR/$stage.json" "$stage" "$RUN_ID" "$PROFILE_SHA256" "$SOURCE_COMMIT_SHA" "$stage_rate" "$stage_digest" "$USERS" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, stage, run_id, profile_sha, source_commit_sha, confirmed_rate, input_digest, users_raw = sys.argv[1:]
payload = {
    "stage": stage,
    "runId": run_id,
    "profileSha256": profile_sha,
    "sourceCommitSha": source_commit_sha,
    "confirmedRate": confirmed_rate or None,
    "inputDigest": input_digest,
    "completedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}
if stage == "seed" or stage in {"smoke", "ramp", "spike", "soak", "scale-step", "capacity-stress"} or stage.startswith("baseline-"):
    payload.update({
        "fixtureId": stage,
        "fixtureResultPath": f"fixtures/{stage}.json",
        "fixtureExpectedUsers": int(users_raw),
    })
Path(output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

run_stage_once() {
  local stage="$1"
  shift
  if [[ -f "$STAGE_DIR/$stage.json" ]] && stage_is_complete "$stage"; then
    echo "[b01] stage=$stage already complete for this run/profile/rate; skipping"
    return 0
  elif [[ -f "$STAGE_DIR/$stage.json" ]]; then
    echo "[b01] stage=$stage exists but profile/rate inputs differ; use a new --run-id instead of rerunning (safety input digest also changed or is missing)" >&2
    exit 2
  fi
  "$@"
  mark_stage_complete "$stage"
}

verify_account() {
  local observed
  observed="$(run_aws_json sts get-caller-identity --region "$REGION" --query Account --output text 2>/dev/null || true)"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "0000"
    return 0
  fi
  if [[ "$observed" != "$EXPECTED_ACCOUNT_ID" ]]; then
    echo "observed AWS account does not match --expected-account-id; refusing to run" >&2
    exit 1
  fi
  echo "$observed"
}

validate_runner_instance() {
  python3 - "$@" <<'PY'
import json
import sys

payload, instance_id, environment, expected_type = sys.argv[1:]
reservations = json.loads(payload).get("Reservations", [])
instances = [item for reservation in reservations for item in reservation.get("Instances", [])]
if len(instances) != 1 or instances[0].get("InstanceId") != instance_id:
    raise SystemExit("Runner instance was not resolved exactly")
instance = instances[0]
tags = {tag.get("Key"): tag.get("Value", "") for tag in instance.get("Tags", [])}
if instance.get("State", {}).get("Name") != "running":
    raise SystemExit("Runner EC2 is not running")
if instance.get("InstanceType") != expected_type:
    raise SystemExit("Runner EC2 Instance Type does not match --runner-instance-type")
if not instance.get("IamInstanceProfile", {}).get("Arn"):
    raise SystemExit("Runner EC2 has no IAM instance profile")
if not instance.get("SecurityGroups"):
    raise SystemExit("Runner EC2 has no security group")
if tags.get("Environment") != environment or tags.get("Service") != "travel-planner-load-runner":
    raise SystemExit("Runner EC2 tags do not match the approved environment/service")
print(json.dumps({
    "status": "validated",
    "instanceId": instance_id,
    "instanceType": instance.get("InstanceType"),
    "iamInstanceProfileArn": instance["IamInstanceProfile"]["Arn"],
    "securityGroupIds": sorted(group["GroupId"] for group in instance["SecurityGroups"]),
    "tags": {"Environment": tags.get("Environment"), "Service": tags.get("Service")},
}, sort_keys=True))
PY
}

validate_runner_ssm() {
  python3 - "$1" <<'PY'
import json
import sys

items = json.loads(sys.argv[1]).get("InstanceInformationList", [])
if len(items) != 1 or items[0].get("PingStatus") != "Online":
    raise SystemExit("Runner EC2 is not SSM Online")
PY
}

eks_target_stage() {
  echo "[b01] target: verifying account/ALB/Runner and EKS adapter contract"
  local observed_account
  observed_account="$(verify_account)"
  local account_last4 account_sha256
  account_last4="${observed_account: -4}"
  account_sha256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$observed_account")"
  local adapter="$REPOSITORY_ROOT/scripts/loadtest/aws/eks_target_adapter.py"
  local validation_dir
  validation_dir="$(mktemp -d "${TMPDIR:-/tmp}/scrum53-eks-target.XXXXXX")"

  mkdir -p "$EVIDENCE_ROOT/aws"
  local alb_json target_group_arn target_health_json dns_name
  local runner_json runner_ssm_json runner_validation_json nodegroup_json asg_name asg_json
  alb_json="$(run_aws_json elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" --region "$REGION")"
  echo "$alb_json" > "$EVIDENCE_ROOT/aws/resource-config.json"
  if [[ "$DRY_RUN" == "1" ]]; then
    dns_name="dry-run.invalid"
    target_group_arn=""
    runner_validation_json='{"status":"dry-run"}'
    nodegroup_json='{"status":"dry-run"}'
    target_health_json='{"status":"dry-run"}'
    asg_name=""
    asg_json='{"status":"dry-run"}'
  else
    dns_name="$(python3 -c "import json,sys; print(json.load(sys.stdin)['LoadBalancers'][0]['DNSName'])" <<<"$alb_json")"
    target_group_arn="$(run_aws_json elbv2 describe-target-groups --load-balancer-arn "$ALB_ARN" --region "$REGION" \
      | python3 -c "import json,sys; groups=json.load(sys.stdin)['TargetGroups']; print(groups[0]['TargetGroupArn'] if groups else '')")"
    if [[ -z "$target_group_arn" ]]; then
      echo "EKS ALB has no target group" >&2
      exit 1
    fi
    runner_json="$(run_aws_json ec2 describe-instances --instance-ids "$RUNNER_ID" --region "$REGION")"
    runner_validation_json="$(validate_runner_instance "$runner_json" "$RUNNER_ID" "$ENVIRONMENT" "$RUNNER_INSTANCE_TYPE")"
    runner_ssm_json="$(run_aws_json ssm describe-instance-information --filters "Key=InstanceIds,Values=$RUNNER_ID" --region "$REGION")"
    validate_runner_ssm "$runner_ssm_json"
    nodegroup_json="$(run_aws_json eks describe-nodegroup --cluster-name "$EKS_CLUSTER_NAME" --nodegroup-name "$EKS_NODE_GROUP_NAME" --region "$REGION")"
    target_health_json="$(run_aws_json elbv2 describe-target-health --target-group-arn "$target_group_arn" --region "$REGION")"
    printf '%s\n' "$nodegroup_json" > "$validation_dir/nodegroup.json"
    printf '%s\n' "$target_health_json" > "$validation_dir/target-health.json"
    python3 "$adapter" validate \
      --cluster-name "$EKS_CLUSTER_NAME" --node-group-name "$EKS_NODE_GROUP_NAME" \
      --target-group-arn "$target_group_arn" \
      --node-group-json "$validation_dir/nodegroup.json" \
      --target-health-json "$validation_dir/target-health.json" \
      > "$validation_dir/validated.json"
    python3 - "$validation_dir/validated.json" "$validation_dir/node-summary.json" "$validation_dir/alb-summary.json" <<'PY'
import json
import sys
from pathlib import Path

validated, node_output, alb_output = map(Path, sys.argv[1:])
payload = json.loads(validated.read_text(encoding="utf-8"))
node_output.write_text(json.dumps(payload["nodeGroup"], indent=2) + "\n", encoding="utf-8")
alb_output.write_text(json.dumps(payload["alb"], indent=2) + "\n", encoding="utf-8")
PY
    asg_name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["autoScalingGroupName"])' "$validation_dir/node-summary.json")"
    asg_json="$(run_aws_json autoscaling describe-scaling-activities --auto-scaling-group-name "$asg_name" --region "$REGION" --max-items 20)"
    cp "$validation_dir/node-summary.json" "$EVIDENCE_ROOT/aws/eks-node-group-summary.json"
    cp "$validation_dir/alb-summary.json" "$EVIDENCE_ROOT/aws/eks-alb-target-health.json"
    cp "$validation_dir/alb-summary.json" "$EVIDENCE_ROOT/aws/target-health.json"
  fi
  echo "$runner_validation_json" > "$EVIDENCE_ROOT/aws/runner-validation.json"
  echo "{\"approvedBaseUrl\":\"$BASE_URL\",\"albDnsName\":\"$dns_name\"}" > "$EVIDENCE_ROOT/aws/base-url-validation.json"
  if [[ "$DRY_RUN" != "1" ]]; then
    curl --silent --show-error --max-time 10 --output /dev/null "$BASE_URL/"
  fi
  echo "$asg_json" > "$EVIDENCE_ROOT/aws/asg-activities.json"
  if [[ "$DRY_RUN" == "1" ]]; then
    cat > "$EVIDENCE_ROOT/aws/eks-node-group-summary.json" <<EOF
{"status":"dry-run","clusterName":"$EKS_CLUSTER_NAME","nodeGroupName":"$EKS_NODE_GROUP_NAME","scalingConfig":{"min":2,"desired":2,"max":4}}
EOF
    cat > "$EVIDENCE_ROOT/aws/eks-alb-target-health.json" <<EOF
{"status":"dry-run","targetType":"ip","healthyTargetCount":null}
EOF
    cp "$EVIDENCE_ROOT/aws/eks-alb-target-health.json" "$EVIDENCE_ROOT/aws/target-health.json"
  fi

  python3 "$adapter" commands --cluster-name "$EKS_CLUSTER_NAME" --region "$REGION" \
    --namespace "$BACKEND_NAMESPACE" --deployment "$BACKEND_DEPLOYMENT" \
    > "$EVIDENCE_ROOT/aws/eks-kubectl-commands.json"
  if [[ "$DRY_RUN" == "1" ]]; then
    cat > "$EVIDENCE_ROOT/aws/eks-kubectl-invocation.json" <<'EOF'
{"status":"dry-run","rawOutputStored":false}
EOF
    cat > "$EVIDENCE_ROOT/aws/eks-evidence.json" <<EOF
{"platform":"eks","status":"dry-run","targetPlatform":"eks","nodeGroupName":"$EKS_NODE_GROUP_NAME","hpa":{"desiredReplicas":null,"currentReplicas":null},"backendPods":{"count":null,"placement":[]},"nodeCount":null,"nodeGroupScalingActivities":[],"alb":{"targetType":"ip","healthyTargetCount":null},"sanitization":{"rawKubectlOutputStored":false}}
EOF
  else
    local ssm_parameters command_json command_id invocation_json invocation_status
    ssm_parameters="$(cat "$EVIDENCE_ROOT/aws/eks-kubectl-commands.json")"
    command_json="$(run_aws_json ssm send-command --instance-ids "$EKS_BASTION_ID" \
      --document-name AWS-RunShellScript --comment "SCRUM-53 EKS evidence snapshot" \
      --parameters "$ssm_parameters" --region "$REGION")"
    command_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["Command"]["CommandId"])' <<<"$command_json")"
    invocation_json=''
    invocation_status=''
    for _ in $(seq 1 30); do
      invocation_json="$(run_aws_json ssm get-command-invocation --command-id "$command_id" --instance-id "$EKS_BASTION_ID" --region "$REGION")"
      invocation_status="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("Status", ""))' <<<"$invocation_json")"
      case "$invocation_status" in
        Success) break ;;
        Failed|Cancelled|TimedOut) echo "EKS bastion kubectl snapshot failed: $invocation_status" >&2; exit 1 ;;
      esac
      sleep 2
    done
    if [[ "$invocation_status" != "Success" ]]; then
      echo "Timed out waiting for EKS bastion kubectl snapshot" >&2
      exit 1
    fi
    printf '%s\n' "$invocation_json" > "$validation_dir/invocation.json"
    python3 "$adapter" sanitize-invocation --cluster-name "$EKS_CLUSTER_NAME" \
      --invocation-json "$validation_dir/invocation.json" > "$EVIDENCE_ROOT/aws/eks-kubectl-invocation.json"
    python3 "$adapter" build-evidence --cluster-name "$EKS_CLUSTER_NAME" \
      --invocation-json "$validation_dir/invocation.json" \
      --node-group-summary-json "$validation_dir/node-summary.json" \
      --alb-summary-json "$validation_dir/alb-summary.json" \
      --asg-activities-json "$EVIDENCE_ROOT/aws/asg-activities.json" \
      > "$EVIDENCE_ROOT/aws/eks-evidence.json"
  fi

  python3 - "$EVIDENCE_ROOT/aws/resource-dimensions.json" "$ALB_ARN" "$target_group_arn" "$asg_name" "$DB_INSTANCE_IDENTIFIER" "$CACHE_CLUSTER_ID" "$EKS_CLUSTER_NAME" "$EKS_NODE_GROUP_NAME" <<'PY'
import json
import sys
from pathlib import Path

output, alb_arn, target_group_arn, asg_name, db_identifier, cache_cluster_id, cluster_name, node_group_name = sys.argv[1:]
def suffix(arn, marker, include_marker=False):
    if not arn or marker not in arn:
        return None
    value = arn.split(marker, 1)[1]
    return f"{marker}{value}" if include_marker else value

Path(output).write_text(json.dumps({
    "targetPlatform": "eks",
    "albDimension": suffix(alb_arn, "loadbalancer/"),
    "targetGroupDimension": suffix(target_group_arn, "targetgroup/", include_marker=True),
    "autoScalingGroupName": asg_name or None,
    "clusterName": cluster_name,
    "nodeGroupName": node_group_name,
    "dbInstanceIdentifier": db_identifier or None,
    "cacheClusterId": cache_cluster_id or None,
    "note": "EKS ALB targets Pod IPs; the backing ASG is recorded only from the managed node-group response, never from ALB target IDs.",
}, indent=2) + "\n", encoding="utf-8")
PY

  python3 - "$EVIDENCE_ROOT/metadata.json" "$RUN_ID" "$ENVIRONMENT" "$REGION" "$account_last4" "$account_sha256" \
    "$ALB_ARN" "$asg_name" "$RUNNER_ID" "$RUNNER_INSTANCE_TYPE" "$BASE_URL" "$REPOSITORY_ROOT" \
    "$TARGET_PLATFORM" "$EKS_CLUSTER_NAME" "$EKS_NODE_GROUP_NAME" "$EKS_BASTION_ID" <<'PY'
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

(output, run_id, environment, region, account_last4, account_sha256,
 alb_arn, asg_name, runner_id, runner_instance_type, base_url, repo_root,
 platform, cluster_name, node_group_name, bastion_id) = sys.argv[1:]
commit_sha = subprocess.run(["git", "-C", repo_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
Path(output).write_text(json.dumps({
    "runId": run_id,
    "scenarioId": "B-01",
    "platform": platform,
    "environment": environment,
    "startedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "endedAtUtc": None,
    "commitSha": commit_sha,
    "aws": {
        "accountIdLast4": account_last4,
        "accountIdSha256": account_sha256,
        "accountValidation": "sts-observed-vs-operator-approved-runtime-input",
        "region": region,
        "albArnHash": hashlib.sha256(alb_arn.encode()).hexdigest(),
        "autoScalingGroupName": asg_name or None,
        "runnerInstanceId": runner_id,
        "runnerInstanceType": runner_instance_type,
        "baseUrl": base_url,
        "eksClusterName": cluster_name,
        "eksNodeGroupName": node_group_name,
        "eksBastionIdSha256": hashlib.sha256(bastion_id.encode()).hexdigest(),
    },
}, indent=2) + "\n", encoding="utf-8")
PY
  python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$EVIDENCE_ROOT" RUN_START "B-01 EKS orchestration started" --actor operator 2>/dev/null || true
  rm -rf -- "$validation_dir"
  echo "[b01] EKS target verified: BASE_URL=$BASE_URL evidenceRoot=$EVIDENCE_ROOT"
}

target_stage() {
  if [[ "$TARGET_PLATFORM" == "eks" ]]; then
    eks_target_stage
    return
  fi
  echo "[b01] target: verifying account/ALB/runner"
  local observed_account
  observed_account="$(verify_account)"
  local account_last4 account_sha256
  account_last4="${observed_account: -4}"
  account_sha256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$observed_account")"

  mkdir -p "$EVIDENCE_ROOT/aws"
  local alb_json target_group_arn target_health_json backend_asg_name asg_json dns_name
  local runner_json runner_ssm_json runner_validation_json
  alb_json="$(run_aws_json elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" --region "$REGION")"
  echo "$alb_json" > "$EVIDENCE_ROOT/aws/resource-config.json"
  if [[ "$DRY_RUN" == "1" ]]; then
    dns_name="dry-run.invalid"
    target_group_arn=""
    runner_validation_json='{"status":"dry-run"}'
  else
    dns_name="$(python3 -c "import json,sys; print(json.load(sys.stdin)['LoadBalancers'][0]['DNSName'])" <<<"$alb_json")"
    target_group_arn="$(run_aws_json elbv2 describe-target-groups --load-balancer-arn "$ALB_ARN" --region "$REGION" \
      | python3 -c "import json,sys; groups=json.load(sys.stdin)['TargetGroups']; print(groups[0]['TargetGroupArn'] if groups else '')")"
    runner_json="$(run_aws_json ec2 describe-instances --instance-ids "$RUNNER_ID" --region "$REGION")"
    runner_validation_json="$(validate_runner_instance "$runner_json" "$RUNNER_ID" "$ENVIRONMENT" "$RUNNER_INSTANCE_TYPE")"
    runner_ssm_json="$(run_aws_json ssm describe-instance-information --filters "Key=InstanceIds,Values=$RUNNER_ID" --region "$REGION")"
    validate_runner_ssm "$runner_ssm_json"
  fi
  echo "$runner_validation_json" > "$EVIDENCE_ROOT/aws/runner-validation.json"
  echo "{\"approvedBaseUrl\":\"$BASE_URL\",\"albDnsName\":\"$dns_name\"}" > "$EVIDENCE_ROOT/aws/base-url-validation.json"
  if [[ "$DRY_RUN" != "1" ]]; then
    # This request intentionally accepts a 4xx/5xx application response; the
    # curl exit status still verifies DNS, TCP, TLS and certificate hostname.
    curl --silent --show-error --max-time 10 --output /dev/null "$BASE_URL/"
  fi

  if [[ -n "$target_group_arn" ]]; then
    target_health_json="$(run_aws_json elbv2 describe-target-health --target-group-arn "$target_group_arn" --region "$REGION")"
  else
    target_health_json='{"note":"no target group resolved (dry-run or ALB has none registered)"}'
  fi
  echo "$target_health_json" > "$EVIDENCE_ROOT/aws/target-health.json"

  if [[ "$DRY_RUN" == "1" ]]; then
    backend_asg_name=""
    asg_json='{"note":"dry-run"}'
  else
    backend_target_ids_text="$(python3 -c 'import json,sys; print("\n".join(target.get("Target", {}).get("Id", "") for target in json.loads(sys.argv[1]).get("TargetHealthDescriptions", []) if target.get("TargetHealth", {}).get("State") == "healthy"))' "$target_health_json")"
    mapfile -t backend_target_ids <<<"$backend_target_ids_text"
    if [[ "${#backend_target_ids[@]}" -eq 0 ]]; then
      echo "ALB target group has no healthy backend target" >&2
      exit 1
    fi
    backend_asg_name="$(run_aws_json autoscaling describe-auto-scaling-instances --instance-ids "${backend_target_ids[@]}" --region "$REGION" \
      | python3 -c "import json,sys; items=json.load(sys.stdin)['AutoScalingInstances']; print(items[0]['AutoScalingGroupName'] if items else '')")"
    if [[ -z "$backend_asg_name" ]]; then
      echo "healthy backend target is not attached to an Auto Scaling Group" >&2
      exit 1
    fi
    asg_json="$(run_aws_json autoscaling describe-scaling-activities --auto-scaling-group-name "$backend_asg_name" --region "$REGION" --max-items 20)"
  fi
  echo "$asg_json" > "$EVIDENCE_ROOT/aws/asg-activities.json"

  python3 - "$EVIDENCE_ROOT/aws/resource-dimensions.json" "$ALB_ARN" "$target_group_arn" "$backend_asg_name" "$DB_INSTANCE_IDENTIFIER" "$CACHE_CLUSTER_ID" <<'PY'
import json
import sys
from pathlib import Path

output, alb_arn, target_group_arn, asg_name, db_identifier, cache_cluster_id = sys.argv[1:]
def suffix(arn, marker, include_marker=False):
    if not arn or marker not in arn:
        return None
    value = arn.split(marker, 1)[1]
    return f"{marker}{value}" if include_marker else value

Path(output).write_text(json.dumps({
    "albDimension": suffix(alb_arn, "loadbalancer/"),
    "targetGroupDimension": suffix(target_group_arn, "targetgroup/", include_marker=True),
    "autoScalingGroupName": asg_name or None,
    "dbInstanceIdentifier": db_identifier or None,
    "cacheClusterId": cache_cluster_id or None,
    "note": "CloudWatch dimensions are non-secret identifiers; compare against Terraform outputs/AWS console before Grafana capture.",
}, indent=2) + "\n", encoding="utf-8")
PY

  python3 - "$EVIDENCE_ROOT/metadata.json" "$RUN_ID" "$ENVIRONMENT" "$REGION" "$account_last4" "$account_sha256" \
    "$ALB_ARN" "$backend_asg_name" "$RUNNER_ID" "$RUNNER_INSTANCE_TYPE" "$BASE_URL" "$REPOSITORY_ROOT" <<'PY'
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

(output, run_id, environment, region, account_last4, account_sha256,
 alb_arn, asg_name, runner_id, runner_instance_type, base_url, repo_root) = sys.argv[1:]
commit_sha = subprocess.run(
    ["git", "-C", repo_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
).stdout.strip()
alb_arn_hash = hashlib.sha256(alb_arn.encode()).hexdigest()
Path(output).write_text(json.dumps({
    "runId": run_id,
    "scenarioId": "B-01",
    "platform": "ec2",
    "environment": environment,
    "startedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "endedAtUtc": None,
    "commitSha": commit_sha,
    "aws": {
        "accountIdLast4": account_last4,
        "accountIdSha256": account_sha256,
        "accountValidation": "sts-observed-vs-operator-approved-runtime-input",
        "region": region,
        "albArnHash": alb_arn_hash,
        "autoScalingGroupName": asg_name or None,
        "runnerInstanceId": runner_id,
        "runnerInstanceType": runner_instance_type,
        "baseUrl": base_url,
    },
}, indent=2) + "\n", encoding="utf-8")
PY
  python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$EVIDENCE_ROOT" RUN_START "B-01 orchestration started" --actor operator 2>/dev/null || true
  echo "[b01] target verified: BASE_URL=$BASE_URL evidenceRoot=$EVIDENCE_ROOT"
}

seed_credentials() {
  local fixture_id="${1:-seed}"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] seed-aws-load-data.py --run-id $RUN_ID --users $USERS --reset-fixture --fixture-id $fixture_id" >&2
    return 0
  fi
  for required in DATABASE_HOST DATABASE_NAME DATABASE_SECRET_ARN S3_BUCKET REDIS_HOST REDIS_IAM_USER REDIS_REPLICATION_GROUP_ID; do
    if [[ -z "${!required}" ]]; then echo "--${required,,} is required for seed" >&2; exit 2; fi
  done
  local -a seed_args=(
    --run-id "$RUN_ID" --users "$USERS"
    --expected-account-id "$EXPECTED_ACCOUNT_ID" --region "$REGION"
    --database-host "$DATABASE_HOST" --database-port "$DATABASE_PORT"
    --database-name "$DATABASE_NAME"
    --database-secret-arn "$DATABASE_SECRET_ARN"
    --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT"
    --redis-iam-user "$REDIS_IAM_USER" --redis-replication-group-id "$REDIS_REPLICATION_GROUP_ID"
    --base-url "$BASE_URL" --data-file "$DATA_FILE"
    --reset-fixture --fixture-id "$fixture_id"
    --fixture-result-file "$FIXTURES_DIR/$fixture_id.json"
  )
  mkdir -p "$FIXTURES_DIR"
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/seed-aws-load-data.py" "${seed_args[@]}"
}

seed_stage() {
  echo "[b01] seed: run-id=$RUN_ID users=$USERS"
  seed_credentials "seed"
}

phase_max_vus_override() {
  case "$1" in
    smoke) printf '' ;;
    ramp) printf '%s' "$RAMP_MAX_VUS" ;;
    baseline) printf '%s' "$BASELINE_MAX_VUS" ;;
    spike) printf '%s' "$SPIKE_MAX_VUS" ;;
    soak) printf '%s' "$SOAK_MAX_VUS" ;;
    scale-step) printf '%s' "$SCALE_STEP_MAX_VUS" ;;
    capacity-stress) printf '%s' "$CAPACITY_STRESS_MAX_VUS" ;;
    *) echo "unsupported phase for VU capacity validation: $1" >&2; return 2 ;;
  esac
}

validate_phase_credential_capacity() {
  local phase="$1"
  local override
  override="$(phase_max_vus_override "$phase")"
  python3 - "$PROFILE" "$phase" "$USERS" "$MAX_VUS" "$override" <<'PY'
import json
import sys
from pathlib import Path

profile_path, phase, users_raw, ceiling_raw, override_raw = sys.argv[1:]
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
scenario = profile.get("scenarios", {}).get(phase)
if not isinstance(scenario, dict):
    raise SystemExit(f"profile.scenarios.{phase} is missing")

def positive_integer(raw, label):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise SystemExit(f"{label} must be a positive integer")
    if value < 1 or str(value) != str(raw):
        raise SystemExit(f"{label} must be a positive integer")
    return value

users = positive_integer(users_raw, "--users")
ceiling = positive_integer(ceiling_raw, "--max-vus")
profile_vus = scenario.get("vus") if phase == "smoke" else scenario.get("maxVUs")
effective_vus = positive_integer(override_raw or profile_vus, f"{phase} maxVUs")
profile_limit = positive_integer(profile.get("limits", {}).get("maxVUs"), "profile limits.maxVUs")
if effective_vus > profile_limit:
    raise SystemExit(f"{phase} maxVUs {effective_vus} exceeds profile limits.maxVUs {profile_limit}")
if effective_vus > ceiling:
    raise SystemExit(f"{phase} maxVUs {effective_vus} exceeds operator --max-vus ceiling {ceiling}")
if users < effective_vus:
    raise SystemExit(
        f"--users {users} is smaller than {phase} maxVUs {effective_vus}; "
        "AWS VUs may not share refresh credentials"
    )
print(f"[b01] credential capacity verified: phase={phase} users={users} maxVUs={effective_vus}")
PY
}

k6_phase_stage() {
  local phase="$1"
  local baseline_rep="${2:-}"
  echo "[b01] $phase"
  validate_phase_credential_capacity "$phase"
  if [[ "$phase" == "spike" ]]; then
    require_d005_record_gate
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] refresh credentials before $phase" >&2
    echo "[dry-run] run-aws-b01.sh $phase (RUN_ID=$RUN_ID rate=${CONFIRMED_RATE:-<profile>})" >&2
    return 0
  fi
  for required in K6_IMAGE; do
    if [[ -z "${!required}" ]]; then echo "--k6-image is required for $phase" >&2; exit 2; fi
  done
  local fixture_id="$phase${baseline_rep:+-$baseline_rep}"
  echo "[b01] resetting and refreshing fixture before $fixture_id"
  seed_credentials "$fixture_id"
  export REPOSITORY_ROOT EVIDENCE_ROOT BASE_URL REGION ENVIRONMENT MAX_RATE MAX_VUS
  export K6_IMAGE_DIGEST="$K6_IMAGE" AWS_PROFILE_FILE="$PROFILE" RUN_ID="$RUN_ID"
  export DATA_FILE
  export START_RATE DURATION WARMUP
  export RAMP_PREALLOCATED_VUS RAMP_MAX_VUS
  export BASELINE_PREALLOCATED_VUS BASELINE_MAX_VUS
  export SPIKE_PREALLOCATED_VUS SPIKE_MAX_VUS SPIKE_PEAK_MULTIPLIER SPIKE_HOLD
  export SOAK_PREALLOCATED_VUS SOAK_MAX_VUS SCALE_STEP_PREALLOCATED_VUS SCALE_STEP_MAX_VUS
  export CAPACITY_STRESS_PREALLOCATED_VUS CAPACITY_STRESS_MAX_VUS
  export AWS_SLO_CONTRACT_FILE="$SLO_CONTRACT"
  if [[ -n "$CONFIRMED_RATE" ]]; then export CONFIRMED_RATE; fi
  if [[ "$phase" == "baseline" ]]; then
    if [[ -n "$baseline_rep" ]]; then
      "$REPOSITORY_ROOT/scripts/loadtest/aws/run-aws-b01.sh" baseline "$baseline_rep"
    else
      for rep in 1 2 3; do
        "$REPOSITORY_ROOT/scripts/loadtest/aws/run-aws-b01.sh" baseline "$rep"
      done
    fi
  else
    "$REPOSITORY_ROOT/scripts/loadtest/aws/run-aws-b01.sh" "$phase"
  fi
}

validate_confirmed_rate() {
  if [[ -z "$CONFIRMED_RATE" ]]; then
    echo "--confirmed-rate is required for $MODE" >&2
    exit 2
  fi
  python3 - "$CONFIRMED_RATE" "$MAX_RATE" <<'PY'
import math
import sys

confirmed_raw, operator_max_raw = sys.argv[1:]
try:
    confirmed = float(confirmed_raw)
    operator_max = float(operator_max_raw)
except (TypeError, ValueError):
    raise SystemExit("--confirmed-rate and --max-rate must be finite numbers")
if not math.isfinite(confirmed) or confirmed <= 0:
    raise SystemExit("--confirmed-rate must be a positive finite number")
if not math.isfinite(operator_max) or operator_max <= 0:
    raise SystemExit("--max-rate must be a positive finite number")
if confirmed > operator_max:
    raise SystemExit(f"--confirmed-rate {confirmed_raw} exceeds --max-rate {operator_max_raw}")
PY
}

require_baseline_candidate_gate() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would require a passed baseline-candidate.json before D-005/Spike" >&2
    return 0
  fi
  local candidate_path="$EVIDENCE_ROOT/baseline-candidate.json"
  if [[ ! -f "$candidate_path" ]]; then
    echo "baseline-candidate.json is missing; Baseline x3 gate must pass before D-005 or Spike" >&2
    exit 2
  fi
  python3 - "$candidate_path" "$RUN_ID" "$CONFIRMED_RATE" "$SOURCE_COMMIT_SHA" "$PROFILE_SHA256" <<'PY'
import json
import math
import sys
from pathlib import Path

candidate_path, run_id, confirmed_raw, source_sha, profile_sha = sys.argv[1:]
payload = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
candidate = payload.get("baselineCandidate")
if payload.get("runId") != run_id:
    raise SystemExit("baseline-candidate.json runId does not match this run")
if payload.get("sourceCommitSha") != source_sha:
    raise SystemExit("baseline-candidate.json source commit does not match this run")
if payload.get("profileSha256") != profile_sha or payload.get("profileShaConsistent") is not True:
    raise SystemExit("baseline-candidate.json profile digest does not match this run")
if payload.get("inputDigestContractPassed") is not True:
    raise SystemExit("baseline-candidate.json input digest contract has not passed")
if payload.get("digestGatePassed") is not True:
    raise SystemExit("baseline-candidate.json digest gate has not passed")
if not isinstance(candidate, dict) or candidate.get("frozen") is not True:
    raise SystemExit("Baseline x3 gate has not passed; refusing D-005/Spike")
if candidate.get("rateMatchesConfirmedRate") is not True:
    raise SystemExit("Baseline rate does not match --confirmed-rate; refusing D-005/Spike")
try:
    confirmed = float(confirmed_raw)
    recorded = float(payload.get("confirmedRate"))
except (TypeError, ValueError):
    raise SystemExit("baseline-candidate.json has no valid confirmedRate")
if not math.isfinite(confirmed) or not math.isfinite(recorded) or confirmed != recorded:
    raise SystemExit("baseline-candidate.json confirmedRate does not match --confirmed-rate")
PY
}

require_d005_record_gate() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would require D-005 baseline gate and d005-arrival-rate.json before Spike" >&2
    return 0
  fi
  require_baseline_candidate_gate
  if ! stage_is_complete d005; then
    echo "D-005 d005-record stage is missing or stale; refusing Spike" >&2
    exit 2
  fi
  if [[ ! -f "$EVIDENCE_ROOT/d005-arrival-rate.json" ]]; then
    echo "d005-arrival-rate.json is missing; refusing Spike" >&2
    exit 2
  fi
  python3 - "$EVIDENCE_ROOT/d005-arrival-rate.json" "$EVIDENCE_ROOT/baseline-candidate.json" "$RUN_ID" "$CONFIRMED_RATE" "$SOURCE_COMMIT_SHA" "$PROFILE_SHA256" <<'PY'
import hashlib
import json
import math
import sys
from pathlib import Path

record_path, candidate_path, run_id, confirmed_raw, source_sha, profile_sha = sys.argv[1:]
record = json.loads(Path(record_path).read_text(encoding="utf-8"))
candidate_sha = hashlib.sha256(Path(candidate_path).read_bytes()).hexdigest()
if record.get("runId") != run_id:
    raise SystemExit("d005-arrival-rate.json runId does not match this run")
if record.get("baselineCandidateSha256") != candidate_sha:
    raise SystemExit("d005-arrival-rate.json baseline candidate is stale; rerun D-005 gate")
if record.get("sourceCommitSha") != source_sha or record.get("profileSha256") != profile_sha:
    raise SystemExit("d005-arrival-rate.json source/profile digest does not match this run")
try:
    recorded = float(record.get("arrivalRate"))
    confirmed = float(confirmed_raw)
except (TypeError, ValueError):
    raise SystemExit("d005-arrival-rate.json has no valid arrivalRate")
if not math.isfinite(recorded) or not math.isfinite(confirmed) or recorded != confirmed:
    raise SystemExit("d005-arrival-rate.json does not match --confirmed-rate")
PY
}

d005_record_stage() {
  # Record the D-005 rate only after validate-aws-run.py has produced a
  # passing Baseline x3 candidate. This gives the subsequent Spike gate a
  # durable, hash-bound decision artifact rather than trusting an ephemeral
  # --confirmed-rate CLI argument.
  echo "[b01] d005-record: rate=$CONFIRMED_RATE"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would write $EVIDENCE_ROOT/d005-arrival-rate.json" >&2
    return 0
  fi
  validate_confirmed_rate
  for rep in 1 2 3; do
    if ! stage_is_complete "baseline-$rep"; then
      echo "baseline-$rep is not complete; refusing to record D-005" >&2
      exit 2
    fi
  done
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/validate-aws-run.py" \
    "$EVIDENCE_ROOT" --confirmed-rate "$CONFIRMED_RATE" --baseline-candidate-only
  local profile_sha256
  profile_sha256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$PROFILE")"
  local candidate_sha256
  candidate_sha256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$EVIDENCE_ROOT/baseline-candidate.json")"
  python3 - "$EVIDENCE_ROOT/d005-arrival-rate.json" "$RUN_ID" "$CONFIRMED_RATE" "${MAX_VUS:-}" "$profile_sha256" "$PROFILE" "$candidate_sha256" "$SOURCE_COMMIT_SHA" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, run_id, rate, max_vus, profile_sha256, profile_path, candidate_sha256, source_commit_sha = sys.argv[1:]
Path(output).write_text(json.dumps({
    "runId": run_id,
    "note": "This records the D-005 rate only after validate-aws-run.py baselineCandidate.frozen=true.",
    "arrivalRate": float(rate),
    "maxVusCeiling": float(max_vus) if max_vus else None,
    "profilePath": profile_path,
    "profileSha256": profile_sha256,
    "sourceCommitSha": source_commit_sha,
    "baselineCandidatePath": "baseline-candidate.json",
    "baselineCandidateSha256": candidate_sha256,
    "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2) + "\n", encoding="utf-8")
PY
  echo "[b01] d005-arrival-rate.json written"
}

evidence_stage() {
  echo "[b01] evidence: Grafana Annotation + Query (PNG excluded; see Plan04/D-003)"
  mkdir -p "$EVIDENCE_ROOT/grafana/queries"
  if [[ -n "$GRAFANA_URL" && -n "$GRAFANA_ADMIN_USER" && -n "$GRAFANA_ADMIN_PASSWORD" && "$DRY_RUN" != "1" ]]; then
    python3 - "$EVIDENCE_ROOT" "$GRAFANA_URL" "$GRAFANA_ADMIN_USER" "$GRAFANA_ADMIN_PASSWORD" "$RUN_ID" "${TARGET_PLATFORM:-ec2}" <<'PY'
import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

evidence_root, url, user, password, run_id, target_platform = sys.argv[1:]
evidence_root = Path(evidence_root)
EVENT_TAGS = {"RUN_START": "test-start", "RUN_END": "test-end"}
auth = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
results = []
paths = [evidence_root / "operations.jsonl"] + sorted((evidence_root / "k6").glob("*/operations.jsonl"))
for path in paths:
    if not path.exists():
        continue
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        name = event.get("event")
        if name not in EVENT_TAGS:
            continue
        import datetime
        time_ms = int(datetime.datetime.fromisoformat(event["ts"].replace("Z", "+00:00")).timestamp() * 1000)
        payload = {
            "time": time_ms,
            "tags": ["scenario:B-01", f"platform:{target_platform}", f"run:{run_id}", EVENT_TAGS[name]],
            "text": f"{name}: {str(event.get('detail', ''))[:200]}",
        }
        request = Request(
            f"{url.rstrip('/')}/api/annotations",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                results.append({"status": response.status, "time": time_ms, "tags": payload["tags"]})
        except (HTTPError, URLError) as error:
            results.append({"status": "error", "detail": str(error), "time": time_ms, "tags": payload["tags"]})
(evidence_root / "grafana" / "annotations.json").write_text(
    json.dumps({"grafanaUrl": url, "annotationCount": len(results), "results": results}, indent=2) + "\n",
    encoding="utf-8",
)
print(f"[grafana] annotations={len(results)}")
PY
  else
    echo '{"status":"not-published","reason":"--grafana-url/--grafana-user/--grafana-password not supplied"}' \
      > "$EVIDENCE_ROOT/grafana/annotations.json"
  fi

  if [[ -n "$PROMETHEUS_URL" && "$DRY_RUN" != "1" ]]; then
    python3 - "$EVIDENCE_ROOT" "$PROMETHEUS_URL" <<'PY'
import json
import sys
import urllib.parse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

evidence_root, base_url = sys.argv[1:]
queries = {
    "core-unexpected-error-rate": (
        "sum(rate(core_unexpected_errors_total[5m])) / sum(rate(core_completed_operations_total[5m]))"
    ),
    "core-success-rate": (
        "sum(rate(core_successful_operations_total[5m])) / sum(rate(core_completed_operations_total[5m]))"
    ),
}
out_dir = Path(evidence_root) / "grafana" / "queries"
out_dir.mkdir(parents=True, exist_ok=True)
for name, promql in queries.items():
    url = f"{base_url.rstrip('/')}/api/v1/query?query={urllib.parse.quote(promql)}"
    try:
        with urlopen(url, timeout=10) as response:
            (out_dir / f"{name}.json").write_bytes(response.read())
    except (HTTPError, URLError) as error:
        (out_dir / f"{name}.json").write_text(json.dumps({"status": "error", "detail": str(error), "query": promql}) + "\n", encoding="utf-8")
print(f"[grafana] queries written to {out_dir}")
PY
  else
    echo '{"status":"not-collected","reason":"--prometheus-url not supplied"}' > "$EVIDENCE_ROOT/grafana/queries/status.json"
  fi
  echo "[b01] evidence collection complete"
}

cleanup_stage() {
  echo "[b01] cleanup: run-id=$RUN_ID"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] cleanup-aws-load-data.py --run-id $RUN_ID --result-file $EVIDENCE_ROOT/cleanup-result.json" >&2
    return 0
  fi
  for required in DATABASE_HOST DATABASE_NAME DATABASE_SECRET_ARN; do
    if [[ -z "${!required}" ]]; then echo "--${required,,} is required for cleanup" >&2; exit 2; fi
  done
  local -a cleanup_args=(
    --run-id "$RUN_ID" --expected-account-id "$EXPECTED_ACCOUNT_ID" --region "$REGION"
    --database-host "$DATABASE_HOST" --database-port "$DATABASE_PORT"
    --database-name "$DATABASE_NAME"
    --database-secret-arn "$DATABASE_SECRET_ARN"
    --result-file "$EVIDENCE_ROOT/cleanup-result.json"
  )
  if [[ -n "$REDIS_HOST" && -n "$REDIS_IAM_USER" && -n "$REDIS_REPLICATION_GROUP_ID" ]]; then
    cleanup_args+=(
      --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT"
      --redis-iam-user "$REDIS_IAM_USER" --redis-replication-group-id "$REDIS_REPLICATION_GROUP_ID"
      --data-file "$DATA_FILE" --base-url "$BASE_URL"
    )
  fi
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/cleanup-aws-load-data.py" "${cleanup_args[@]}"
  echo '{"note":"Cost Explorer reflects usage with a reporting delay; treat any same-day figure as estimated (see B01_OPERATOR_RUNBOOK.md step 6)."}' \
    > "$EVIDENCE_ROOT/aws/cost-note.json"
  python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$EVIDENCE_ROOT" RUN_END "B-01 orchestration finished" --actor operator 2>/dev/null || true
  # target_stage wrote metadata.json with endedAtUtc=null (the run wasn't over
  # yet). Fill it in now that cleanup has run, so Plan05's export-grafana-evidence.py
  # has a fixed UTC range to work from without requiring an explicit operator override.
  python3 - "$EVIDENCE_ROOT/metadata.json" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
metadata = json.loads(path.read_text(encoding="utf-8"))
metadata["endedAtUtc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
PY
}

provisional_review_stage() {
  # An inventory, not a verdict: lists what evidence exists so far so the
  # human approving D-006 has a checklist, without this script claiming to
  # judge SLO pass/fail itself (that stays validate-aws-run.py's job).
  echo "[b01] provisional-review: building evidence inventory"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would write $EVIDENCE_ROOT/provisional-review.json" >&2
    return 0
  fi
  python3 - "$EVIDENCE_ROOT" "$RUN_ID" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

evidence_root, run_id = sys.argv[1:]
root = Path(evidence_root)
phase_dirs = sorted(p.name for p in (root / "k6").glob("*") if p.is_dir()) if (root / "k6").exists() else []
Path(evidence_root, "provisional-review.json").write_text(json.dumps({
    "runId": run_id,
    "note": "Inventory only, not a pass/fail verdict — run validate-aws-run.py for the gate result before approving D-006.",
    "phasesPresent": phase_dirs,
    "d005RecordPresent": (root / "d005-arrival-rate.json").exists(),
    "cleanupResultPresent": (root / "cleanup-result.json").exists(),
    "generatedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2) + "\n", encoding="utf-8")
PY
  echo "[b01] provisional-review.json written — review it and $EVIDENCE_ROOT/*/summary.json before approving D-006"
}

freeze_stage() {
  echo "[b01] freeze: approvedBy=$SLO_FREEZE_APPROVED_BY"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would write $EVIDENCE_ROOT/freeze-metadata.json" >&2
    return 0
  fi
  if [[ -z "$SLO_FREEZE_APPROVED_BY" ]]; then echo "--slo-freeze-approved-by is required for freeze" >&2; exit 2; fi
  if [[ ! -f "$EVIDENCE_ROOT/provisional-review.json" ]]; then
    echo "provisional-review.json not found under $EVIDENCE_ROOT; run provisional-review before freeze" >&2
    exit 2
  fi
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/build-freeze-input-manifest.py" \
    --run-id "$RUN_ID" --source-sha "$SOURCE_COMMIT_SHA" \
    --slo-contract "$SLO_CONTRACT" --b01-profile "$PROFILE" \
    --baseline-candidate "$EVIDENCE_ROOT/baseline-candidate.json" \
    --d005-rate-file "$EVIDENCE_ROOT/d005-arrival-rate.json" \
    --spike-run-dir "$EVIDENCE_ROOT/k6/spike" \
    --output "$EVIDENCE_ROOT/freeze-input-manifest.json" >/dev/null
  python3 - "$EVIDENCE_ROOT/freeze-metadata.json" "$EVIDENCE_ROOT/freeze-input-manifest.json" "$RUN_ID" "$SLO_FREEZE_APPROVED_BY" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, manifest_path, run_id, approved_by = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
Path(output).write_text(json.dumps({
    "runId": run_id,
    "sloVersion": "v1.0-frozen",
    "approvedBy": approved_by,
    "approvedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "freezeInputManifest": "freeze-input-manifest.json",
    "freezeInputDigest": manifest["inputDigest"],
    "sloContractSha256": manifest["contract"]["sha256"],
    "note": "B-02/Recovery must not be invoked before this file exists (D-006, TEAM_MEMBER_B01_ACTION_REQUEST.md §4.2).",
}, indent=2) + "\n", encoding="utf-8")
PY
  echo "[b01] freeze-metadata.json written"
}

export_stage() {
  echo "[b01] export: final safety scan + checksum manifest + S3 upload"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] upload-aws-evidence.py --run-id $RUN_ID --evidence-root $EVIDENCE_ROOT" >&2
    return 0
  fi
  # The export gate: this is the one place in the whole pipeline that can
  # actually enforce "final export happens after D-006 freeze" in code —
  # everything upstream of this is advisory/procedural. A standalone
  # `export` invocation goes through this same check, not just `all`.
  if [[ ! -f "$EVIDENCE_ROOT/freeze-metadata.json" ]]; then
    echo "freeze-metadata.json not found under $EVIDENCE_ROOT; refusing to export before D-006 freeze (run: freeze --slo-freeze-approved-by <name>)" >&2
    exit 2
  fi
  if [[ -z "$S3_BUCKET" ]]; then echo "--s3-bucket is required for export" >&2; exit 2; fi
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/upload-aws-evidence.py" \
    --run-id "$RUN_ID" --evidence-root "$EVIDENCE_ROOT" --data-file "$DATA_FILE" \
    --expected-account-id "$EXPECTED_ACCOUNT_ID" --region "$REGION" \
    --s3-bucket "$S3_BUCKET" --s3-prefix "$S3_PREFIX"
  python3 - "$EVIDENCE_ROOT/export-complete.json" "$RUN_ID" "$S3_BUCKET" "$S3_PREFIX" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, run_id, bucket, prefix = sys.argv[1:]
Path(output).write_text(json.dumps({
    "runId": run_id,
    "s3Bucket": bucket,
    "s3Prefix": prefix,
    "completedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "note": "Local proof-of-export marker for check-destroy-gate.sh. Does not itself re-verify the S3 objects.",
}, indent=2) + "\n", encoding="utf-8")
PY
  echo "[b01] export-complete.json written — safe to run check-destroy-gate.sh before any teardown"
}

case "$MODE" in
  target)
    run_stage_once target target_stage
    ;;
  seed)
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    ;;
  smoke)
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    run_stage_once smoke k6_phase_stage smoke
    ;;
  ramp)
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    run_stage_once ramp k6_phase_stage ramp
    echo "[b01] Ramp complete. Review $EVIDENCE_ROOT/k6/ramp/summary.json, decide D-005, then re-run with:"
    echo "      orchestrate-aws-b01.sh all --run-id $RUN_ID --confirmed-rate <rate> ..."
    ;;
  baseline)
    validate_confirmed_rate
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    for rep in 1 2 3; do
      run_stage_once "baseline-$rep" k6_phase_stage baseline "$rep"
    done
    ;;
  d005-record)
    validate_confirmed_rate
    run_stage_once d005 d005_record_stage
    ;;
  spike)
    validate_confirmed_rate
    require_d005_record_gate
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    run_stage_once spike k6_phase_stage spike
    ;;
  soak)
    validate_confirmed_rate
    require_d005_record_gate
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    run_stage_once soak k6_phase_stage soak
    ;;
  scale-step)
    validate_confirmed_rate
    require_d005_record_gate
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    run_stage_once scale-step k6_phase_stage scale-step
    ;;
  capacity-stress)
    validate_confirmed_rate
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    run_stage_once capacity-stress k6_phase_stage capacity-stress
    ;;
  evidence)
    run_stage_once evidence evidence_stage
    ;;
  cleanup)
    run_stage_once cleanup cleanup_stage
    ;;
  provisional-review)
    run_stage_once provisional-review provisional_review_stage
    ;;
  freeze)
    run_stage_once freeze freeze_stage
    ;;
  export)
    run_stage_once export export_stage
    ;;
  all)
    run_stage_once target target_stage
    run_stage_once seed seed_stage
    run_stage_once smoke k6_phase_stage smoke
    run_stage_once ramp k6_phase_stage ramp
    if [[ -z "$CONFIRMED_RATE" ]]; then
      echo "[b01] Ramp complete; D-005 needs an operator decision before Baseline/Spike can run."
      echo "      Review $EVIDENCE_ROOT/k6/ramp/summary.json, then re-run:"
      echo "      orchestrate-aws-b01.sh all --run-id $RUN_ID --confirmed-rate <rate> ..."
      exit 0
    fi
    validate_confirmed_rate
    for rep in 1 2 3; do
      run_stage_once "baseline-$rep" k6_phase_stage baseline "$rep"
    done
    run_stage_once d005 d005_record_stage
    run_stage_once spike k6_phase_stage spike
    run_stage_once evidence evidence_stage
    run_stage_once cleanup cleanup_stage
    run_stage_once provisional-review provisional_review_stage
    if [[ -z "$SLO_FREEZE_APPROVED_BY" ]]; then
      echo "[b01] Provisional review complete; D-006 needs an operator decision before final export."
      echo "      Review $EVIDENCE_ROOT/provisional-review.json and run validate-aws-run.py $EVIDENCE_ROOT --confirmed-rate $CONFIRMED_RATE, then re-run:"
      echo "      orchestrate-aws-b01.sh all --run-id $RUN_ID --confirmed-rate $CONFIRMED_RATE --slo-freeze-approved-by <name> ..."
      exit 0
    fi
    run_stage_once freeze freeze_stage
    run_stage_once export export_stage
    echo "[b01] all complete. Ephemeral resource teardown (terraform destroy) is a separate, explicitly-approved step —"
    echo "      run scripts/loadtest/aws/check-destroy-gate.sh $EVIDENCE_ROOT first."
    ;;
esac
