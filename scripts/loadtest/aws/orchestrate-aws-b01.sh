#!/usr/bin/env bash
# Orchestrate an AWS B-01 execution end to end, per
# aws-load-test-handoff/plans/03_AWS_B01_EXECUTION_PLAN.md and
# aws-load-test-handoff/runbooks/B01_OPERATOR_RUNBOOK.md:
#
#   target -> seed -> smoke -> ramp -> [operator decides D-005] ->
#   baseline x3 -> spike -> export (Grafana Annotation + Query, PNG excluded
#   for now — see D-003/Plan04) -> safety scan + S3 upload -> cleanup ->
#   cost note
#
# This script only parses flags and resolves the AWS target once; it then
# delegates one phase at a time to run-aws-b01.sh, exporting the resolved
# env vars every phase needs (mirrors run-compose-rehearsal.sh's
# export-then-delegate structure). seed-aws-load-data.py, cleanup-aws-load-data.py,
# and upload-aws-evidence.py are consumed as-is (#247/#249, merged) — this
# script does not reimplement any of their logic.
#
# D-005 (the normal arrival-rate) can only be set after a human reviews this
# run's Ramp output (see decisions/OPEN_DECISIONS.md) — it is not something
# this script can decide on its own. `all` therefore runs through Ramp and
# stops unless --confirmed-rate is already supplied; baseline/spike/export/
# cleanup/all-with-a-rate are meant to be a second invocation with the same
# --run-id after that review.
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MODE="all"
PROFILE="$REPOSITORY_ROOT/load-tests/aws/profiles/ec2-b01.json"
REGION=""
ENVIRONMENT=""
EXPECTED_ACCOUNT_ID=""
ALB_ARN=""
RUNNER_ID=""
S3_BUCKET=""
S3_PREFIX="evidence/aws-load-tests"
DRY_RUN=0
MAX_RATE=""
MAX_VUS=""
RUN_ID=""
K6_IMAGE=""
CONFIRMED_RATE=""
USERS=20
DATABASE_HOST=""
DATABASE_PORT=5432
DATABASE_NAME=""
DATABASE_USER=""
DATABASE_SECRET_ARN=""
REDIS_HOST=""
REDIS_PORT=6379
REDIS_SECRET_ARN=""
GRAFANA_URL="${GRAFANA_URL:-}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-}"
PROMETHEUS_URL=""

usage() {
  cat <<'USAGE'
usage: orchestrate-aws-b01.sh [target|seed|smoke|ramp|baseline|spike|export|cleanup|all] [options]

Required:
  --profile PATH                 AWS load-test profile JSON (default: load-tests/aws/profiles/ec2-b01.json)
  --region REGION
  --environment ENVIRONMENT
  --expected-account-id ID       12-digit AWS account ID this run is approved to target
  --alb-arn ARN                  Exact ALB ARN to verify and resolve BASE_URL from
  --runner-id INSTANCE_ID        This Runner EC2's instance ID (verifies InService, resolves ASG name)
  --s3-prefix PREFIX             Default: evidence/aws-load-tests
  --dry-run                      Skip real aws/docker calls; print the planned actions
  --max-rate RATE                Operator ceiling on top of profile.limits.maxRate
  --max-vus VUS                  Operator ceiling on top of profile.limits.maxVUs

Also required for most modes:
  --s3-bucket NAME                (seed/export/all) evidence S3 bucket
  --k6-image DIGEST                (smoke/ramp/baseline/spike/all) digest-pinned k6 image
  --database-host/--database-name/--database-user/--database-secret-arn   (seed/cleanup/all)
  --redis-host/--redis-secret-arn                                        (seed/cleanup/all; omit together to skip Redis)
  --confirmed-rate RATE            (baseline/spike/export "all" after Ramp) D-005 operator-confirmed arrival-rate

Optional:
  --run-id ID                     Default: aws-b01-<UTC timestamp>
  --users N                       Default: 20
  --database-port PORT            Default: 5432
  --redis-port PORT               Default: 6379
  --grafana-url / --grafana-user / --grafana-password   (export/all) skip annotation publish if omitted
  --prometheus-url URL            (export/all) skip Query JSON collection if omitted
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    target|seed|smoke|ramp|baseline|spike|export|cleanup|all) MODE="$1"; shift ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="$2"; shift 2 ;;
    --alb-arn) ALB_ARN="$2"; shift 2 ;;
    --runner-id) RUNNER_ID="$2"; shift 2 ;;
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
    --database-user) DATABASE_USER="$2"; shift 2 ;;
    --database-secret-arn) DATABASE_SECRET_ARN="$2"; shift 2 ;;
    --redis-host) REDIS_HOST="$2"; shift 2 ;;
    --redis-port) REDIS_PORT="$2"; shift 2 ;;
    --redis-secret-arn) REDIS_SECRET_ARN="$2"; shift 2 ;;
    --grafana-url) GRAFANA_URL="$2"; shift 2 ;;
    --grafana-user) GRAFANA_ADMIN_USER="$2"; shift 2 ;;
    --grafana-password) GRAFANA_ADMIN_PASSWORD="$2"; shift 2 ;;
    --prometheus-url) PROMETHEUS_URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for required in REGION ENVIRONMENT EXPECTED_ACCOUNT_ID ALB_ARN RUNNER_ID MAX_RATE MAX_VUS; do
  if [[ -z "${!required}" ]]; then
    echo "--${required,,} is required" >&2
    exit 2
  fi
done
if [[ ! "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "--expected-account-id must be exactly 12 digits" >&2
  exit 2
fi
if [[ ! -f "$PROFILE" ]]; then
  echo "--profile file does not exist: $PROFILE" >&2
  exit 2
fi
python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/validate-aws-profile.py" "$PROFILE"

RUN_ID="${RUN_ID:-aws-b01-$(date -u +%Y%m%d-%H%M%S)}"
EVIDENCE_ROOT="$REPOSITORY_ROOT/evidence/aws-load-tests/$RUN_ID"
DATA_FILE="$EVIDENCE_ROOT/data.json"
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

target_stage() {
  echo "[b01] target: verifying account/ALB/runner"
  local observed_account
  observed_account="$(verify_account)"
  local account_last4 account_sha256
  account_last4="${observed_account: -4}"
  account_sha256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$observed_account")"

  mkdir -p "$EVIDENCE_ROOT/aws"
  local alb_json target_group_arn target_health_json asg_name asg_json dns_name
  alb_json="$(run_aws_json elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" --region "$REGION")"
  echo "$alb_json" > "$EVIDENCE_ROOT/aws/resource-config.json"
  if [[ "$DRY_RUN" == "1" ]]; then
    dns_name="dry-run.invalid"
    target_group_arn=""
  else
    dns_name="$(python3 -c "import json,sys; print(json.load(sys.stdin)['LoadBalancers'][0]['DNSName'])" <<<"$alb_json")"
    target_group_arn="$(run_aws_json elbv2 describe-target-groups --load-balancer-arn "$ALB_ARN" --region "$REGION" \
      | python3 -c "import json,sys; groups=json.load(sys.stdin)['TargetGroups']; print(groups[0]['TargetGroupArn'] if groups else '')")"
  fi
  BASE_URL="https://$dns_name"

  if [[ -n "$target_group_arn" ]]; then
    target_health_json="$(run_aws_json elbv2 describe-target-health --target-group-arn "$target_group_arn" --region "$REGION")"
  else
    target_health_json='{"note":"no target group resolved (dry-run or ALB has none registered)"}'
  fi
  echo "$target_health_json" > "$EVIDENCE_ROOT/aws/target-health.json"

  if [[ "$DRY_RUN" == "1" ]]; then
    asg_name=""
  else
    asg_name="$(run_aws_json autoscaling describe-auto-scaling-instances --instance-ids "$RUNNER_ID" --region "$REGION" \
      | python3 -c "import json,sys; items=json.load(sys.stdin)['AutoScalingInstances']; print(items[0]['AutoScalingGroupName'] if items else '')")"
  fi
  if [[ -n "$asg_name" ]]; then
    asg_json="$(run_aws_json autoscaling describe-scaling-activities --auto-scaling-group-name "$asg_name" --region "$REGION" --max-items 20)"
  else
    asg_json='{"note":"Runner instance not found in any ASG (dry-run or --runner-id mismatch)"}'
  fi
  echo "$asg_json" > "$EVIDENCE_ROOT/aws/asg-activities.json"

  python3 - "$EVIDENCE_ROOT/metadata.json" "$RUN_ID" "$ENVIRONMENT" "$REGION" "$account_last4" "$account_sha256" \
    "$ALB_ARN" "$asg_name" "$RUNNER_ID" "$REPOSITORY_ROOT" <<'PY'
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

(output, run_id, environment, region, account_last4, account_sha256,
 alb_arn, asg_name, runner_id, repo_root) = sys.argv[1:]
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
    },
}, indent=2) + "\n", encoding="utf-8")
PY
  python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$EVIDENCE_ROOT" RUN_START "B-01 orchestration started" --actor operator 2>/dev/null || true
  echo "[b01] target verified: BASE_URL=$BASE_URL evidenceRoot=$EVIDENCE_ROOT"
}

seed_stage() {
  echo "[b01] seed: run-id=$RUN_ID users=$USERS"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] seed-aws-load-data.py --run-id $RUN_ID --users $USERS" >&2
    return 0
  fi
  for required in DATABASE_HOST DATABASE_NAME DATABASE_USER DATABASE_SECRET_ARN S3_BUCKET; do
    if [[ -z "${!required}" ]]; then echo "--${required,,} is required for seed" >&2; exit 2; fi
  done
  local -a seed_args=(
    --run-id "$RUN_ID" --users "$USERS"
    --expected-account-id "$EXPECTED_ACCOUNT_ID" --region "$REGION"
    --database-host "$DATABASE_HOST" --database-port "$DATABASE_PORT"
    --database-name "$DATABASE_NAME" --database-user "$DATABASE_USER"
    --database-secret-arn "$DATABASE_SECRET_ARN"
    --base-url "$BASE_URL" --data-file "$DATA_FILE"
  )
  if [[ -n "$REDIS_HOST" && -n "$REDIS_SECRET_ARN" ]]; then
    seed_args+=(--redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" --redis-secret-arn "$REDIS_SECRET_ARN")
  fi
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/seed-aws-load-data.py" "${seed_args[@]}"
}

k6_phase_stage() {
  local phase="$1"
  echo "[b01] $phase"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] run-aws-b01.sh $phase (RUN_ID=$RUN_ID rate=${CONFIRMED_RATE:-<profile>})" >&2
    return 0
  fi
  for required in K6_IMAGE; do
    if [[ -z "${!required}" ]]; then echo "--k6-image is required for $phase" >&2; exit 2; fi
  done
  export REPOSITORY_ROOT EVIDENCE_ROOT BASE_URL REGION ENVIRONMENT MAX_RATE MAX_VUS
  export K6_IMAGE_DIGEST="$K6_IMAGE" AWS_PROFILE_FILE="$PROFILE" RUN_ID="$RUN_ID"
  if [[ -n "$CONFIRMED_RATE" ]]; then export CONFIRMED_RATE; fi
  if [[ "$phase" == "baseline" ]]; then
    for rep in 1 2 3; do
      "$REPOSITORY_ROOT/scripts/loadtest/aws/run-aws-b01.sh" baseline "$rep"
    done
  else
    "$REPOSITORY_ROOT/scripts/loadtest/aws/run-aws-b01.sh" "$phase"
  fi
}

export_stage() {
  echo "[b01] export: Grafana Annotation + Query (PNG excluded; see Plan04/D-003), safety scan + S3 upload"
  mkdir -p "$EVIDENCE_ROOT/grafana/queries"
  if [[ -n "$GRAFANA_URL" && -n "$GRAFANA_ADMIN_USER" && -n "$GRAFANA_ADMIN_PASSWORD" && "$DRY_RUN" != "1" ]]; then
    python3 - "$EVIDENCE_ROOT" "$GRAFANA_URL" "$GRAFANA_ADMIN_USER" "$GRAFANA_ADMIN_PASSWORD" "$RUN_ID" <<'PY'
import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

evidence_root, url, user, password, run_id = sys.argv[1:]
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
            "tags": ["scenario:B-01", "platform:ec2", f"run:{run_id}", EVENT_TAGS[name]],
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

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] upload-aws-evidence.py --run-id $RUN_ID --evidence-root $EVIDENCE_ROOT" >&2
    return 0
  fi
  if [[ -z "$S3_BUCKET" ]]; then echo "--s3-bucket is required for export" >&2; exit 2; fi
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/upload-aws-evidence.py" \
    --run-id "$RUN_ID" --evidence-root "$EVIDENCE_ROOT" --data-file "$DATA_FILE" \
    --expected-account-id "$EXPECTED_ACCOUNT_ID" --region "$REGION" \
    --s3-bucket "$S3_BUCKET" --s3-prefix "$S3_PREFIX"
}

cleanup_stage() {
  echo "[b01] cleanup: run-id=$RUN_ID"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] cleanup-aws-load-data.py --run-id $RUN_ID" >&2
    return 0
  fi
  for required in DATABASE_HOST DATABASE_NAME DATABASE_USER DATABASE_SECRET_ARN; do
    if [[ -z "${!required}" ]]; then echo "--${required,,} is required for cleanup" >&2; exit 2; fi
  done
  local -a cleanup_args=(
    --run-id "$RUN_ID" --expected-account-id "$EXPECTED_ACCOUNT_ID" --region "$REGION"
    --database-host "$DATABASE_HOST" --database-port "$DATABASE_PORT"
    --database-name "$DATABASE_NAME" --database-user "$DATABASE_USER"
    --database-secret-arn "$DATABASE_SECRET_ARN"
  )
  if [[ -n "$REDIS_HOST" && -n "$REDIS_SECRET_ARN" ]]; then
    cleanup_args+=(--redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" --redis-secret-arn "$REDIS_SECRET_ARN" --data-file "$DATA_FILE")
  fi
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/cleanup-aws-load-data.py" "${cleanup_args[@]}"
  echo '{"note":"Cost Explorer reflects usage with a reporting delay; treat any same-day figure as estimated (see B01_OPERATOR_RUNBOOK.md step 6)."}' \
    > "$EVIDENCE_ROOT/aws/cost-note.json"
  python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$EVIDENCE_ROOT" RUN_END "B-01 orchestration finished" --actor operator 2>/dev/null || true
}

case "$MODE" in
  target)
    target_stage
    ;;
  seed)
    target_stage
    seed_stage
    ;;
  smoke)
    target_stage
    seed_stage
    k6_phase_stage smoke
    ;;
  ramp)
    target_stage
    seed_stage
    k6_phase_stage ramp
    echo "[b01] Ramp complete. Review $EVIDENCE_ROOT/k6/ramp/summary.json, decide D-005, then re-run with:"
    echo "      orchestrate-aws-b01.sh baseline --run-id $RUN_ID --confirmed-rate <rate> ..."
    ;;
  baseline)
    if [[ -z "$CONFIRMED_RATE" ]]; then echo "--confirmed-rate is required for baseline" >&2; exit 2; fi
    target_stage
    seed_stage
    k6_phase_stage baseline
    ;;
  spike)
    if [[ -z "$CONFIRMED_RATE" ]]; then echo "--confirmed-rate is required for spike" >&2; exit 2; fi
    target_stage
    seed_stage
    k6_phase_stage spike
    ;;
  export)
    export_stage
    ;;
  cleanup)
    cleanup_stage
    ;;
  all)
    target_stage
    seed_stage
    k6_phase_stage smoke
    k6_phase_stage ramp
    if [[ -z "$CONFIRMED_RATE" ]]; then
      echo "[b01] Ramp complete; D-005 needs an operator decision before Baseline/Spike can run."
      echo "      Review $EVIDENCE_ROOT/k6/ramp/summary.json, then re-run:"
      echo "      orchestrate-aws-b01.sh all --run-id $RUN_ID --confirmed-rate <rate> ..."
      exit 0
    fi
    k6_phase_stage baseline
    k6_phase_stage spike
    export_stage
    cleanup_stage
    echo "[b01] all complete. Run validate-aws-run.py $EVIDENCE_ROOT --confirmed-rate $CONFIRMED_RATE for the gate verdict."
    ;;
esac
