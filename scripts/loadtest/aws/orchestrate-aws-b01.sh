#!/usr/bin/env bash
# Orchestrate an AWS B-01 execution end to end, per
# aws-load-test-handoff/plans/03_AWS_B01_EXECUTION_PLAN.md and the team-lead
# TEAM_MEMBER_B01_ACTION_REQUEST.md §4.2 "B-01 실행 순서":
#
#   target -> seed -> smoke -> ramp -> [operator picks a candidate rate] ->
#   baseline x3 (same rate) -> D-005 arrival-rate record -> spike ->
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
DATABASE_SECRET_ARN=""
REDIS_HOST=""
REDIS_PORT=6379
REDIS_IAM_USER=""
REDIS_REPLICATION_GROUP_ID=""
GRAFANA_URL="${GRAFANA_URL:-}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-}"
PROMETHEUS_URL=""
SLO_FREEZE_APPROVED_BY=""

usage() {
  cat <<'USAGE'
usage: orchestrate-aws-b01.sh [target|seed|smoke|ramp|baseline|spike|evidence|cleanup|provisional-review|freeze|export|all] [options]

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
  --database-host/--database-name/--database-secret-arn   (seed/cleanup/all)
                                    --database-secret-arn must be a dedicated test-only Secret,
                                    JSON {"username":..,"password":..} (never the RDS master secret)
  --redis-host/--redis-iam-user/--redis-replication-group-id
                                    (seed/cleanup/all; omit all three together to skip Redis in cleanup —
                                    seed always requires Redis). ElastiCache RBAC + IAM auth, never a Secret.
  --confirmed-rate RATE            (baseline/spike/all after Ramp) D-005 operator-confirmed arrival-rate
  --slo-freeze-approved-by NAME    (freeze/all after provisional-review) D-006 approver identity (person or role, not a secret)

Optional:
  --run-id ID                     Default: aws-b01-<UTC timestamp>
  --users N                       Default: 20
  --database-port PORT            Default: 5432
  --redis-port PORT               Default: 6379
  --grafana-url / --grafana-user / --grafana-password   (evidence/all) skip annotation publish if omitted
  --prometheus-url URL            (evidence/all) skip Query JSON collection if omitted

Modes:
  target|seed|smoke|ramp|baseline|spike   individual phases, as before
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
    target|seed|smoke|ramp|baseline|spike|evidence|cleanup|provisional-review|freeze|export|all) MODE="$1"; shift ;;
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
    --database-secret-arn) DATABASE_SECRET_ARN="$2"; shift 2 ;;
    --redis-host) REDIS_HOST="$2"; shift 2 ;;
    --redis-port) REDIS_PORT="$2"; shift 2 ;;
    --redis-iam-user) REDIS_IAM_USER="$2"; shift 2 ;;
    --redis-replication-group-id) REDIS_REPLICATION_GROUP_ID="$2"; shift 2 ;;
    --grafana-url) GRAFANA_URL="$2"; shift 2 ;;
    --grafana-user) GRAFANA_ADMIN_USER="$2"; shift 2 ;;
    --grafana-password) GRAFANA_ADMIN_PASSWORD="$2"; shift 2 ;;
    --prometheus-url) PROMETHEUS_URL="$2"; shift 2 ;;
    --slo-freeze-approved-by) SLO_FREEZE_APPROVED_BY="$2"; shift 2 ;;
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
  )
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

d005_record_stage() {
  # A factual record of the rate this run's Baseline x3 actually tested —
  # not a pass/fail verdict (that's validate-aws-run.py's job, run
  # separately, same as Compose's summarize-gate.py). This exists so D-005
  # has a durable artifact distinct from --confirmed-rate just being an
  # ephemeral CLI arg consumed into each phase's own metadata.json.
  echo "[b01] d005-record: rate=$CONFIRMED_RATE"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would write $EVIDENCE_ROOT/d005-arrival-rate.json" >&2
    return 0
  fi
  if [[ -z "$CONFIRMED_RATE" ]]; then echo "--confirmed-rate is required for d005-record" >&2; exit 2; fi
  local profile_sha256
  profile_sha256="$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$PROFILE")"
  python3 - "$EVIDENCE_ROOT/d005-arrival-rate.json" "$RUN_ID" "$CONFIRMED_RATE" "${MAX_VUS:-}" "$profile_sha256" "$PROFILE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, run_id, rate, max_vus, profile_sha256, profile_path = sys.argv[1:]
Path(output).write_text(json.dumps({
    "runId": run_id,
    "note": "This records what Baseline x3 was run at, not whether it passed SLO (see validate-aws-run.py's baselineCandidate).",
    "arrivalRate": float(rate),
    "maxVusCeiling": float(max_vus) if max_vus else None,
    "profilePath": profile_path,
    "profileSha256": profile_sha256,
    "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2) + "\n", encoding="utf-8")
PY
  echo "[b01] d005-arrival-rate.json written"
}

evidence_stage() {
  echo "[b01] evidence: Grafana Annotation + Query (PNG excluded; see Plan04/D-003)"
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
      --data-file "$DATA_FILE"
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
  python3 - "$EVIDENCE_ROOT/freeze-metadata.json" "$RUN_ID" "$SLO_FREEZE_APPROVED_BY" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, run_id, approved_by = sys.argv[1:]
Path(output).write_text(json.dumps({
    "runId": run_id,
    "sloVersion": "v1.0-frozen",
    "approvedBy": approved_by,
    "approvedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
  evidence)
    evidence_stage
    ;;
  cleanup)
    cleanup_stage
    ;;
  provisional-review)
    provisional_review_stage
    ;;
  freeze)
    freeze_stage
    ;;
  export)
    export_stage
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
    d005_record_stage
    k6_phase_stage spike
    evidence_stage
    cleanup_stage
    provisional_review_stage
    if [[ -z "$SLO_FREEZE_APPROVED_BY" ]]; then
      echo "[b01] Provisional review complete; D-006 needs an operator decision before final export."
      echo "      Review $EVIDENCE_ROOT/provisional-review.json and run validate-aws-run.py $EVIDENCE_ROOT --confirmed-rate $CONFIRMED_RATE, then re-run:"
      echo "      orchestrate-aws-b01.sh all --run-id $RUN_ID --confirmed-rate $CONFIRMED_RATE --slo-freeze-approved-by <name> ..."
      exit 0
    fi
    freeze_stage
    export_stage
    echo "[b01] all complete. Ephemeral resource teardown (terraform destroy) is a separate, explicitly-approved step —"
    echo "      run scripts/loadtest/aws/check-destroy-gate.sh $EVIDENCE_ROOT first."
    ;;
esac
