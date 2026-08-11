#!/usr/bin/env bash
# Download an AWS B-01 evidence bundle from S3 to a local directory, then
# (optionally) fill in grafana/* via export-grafana-evidence.py and finalize
# manifest.json via build-evidence-manifest.py — the download direction of
# contracts/EVIDENCE_BUNDLE_CONTRACT.md, per
# aws-load-test-handoff/plans/05_EVIDENCE_EXPORT_PLAN.md.
#
# This is the operator-side counterpart to upload-aws-evidence.py (which runs
# on the Runner right after a test, per scripts/loadtest/aws/orchestrate-aws-b01.sh's
# export_stage). It does not reimplement checksum/safety-scan logic; it
# delegates that to build-evidence-manifest.py.
#
# Grafana access (Plan05 step 1) goes over SSM Port Forwarding, which is an
# interactive, long-running session this script cannot safely start on your
# behalf — it prints the exact `aws ssm start-session` command and waits for
# you to run it in another terminal before continuing.
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

RUN_ID=""
S3_BUCKET=""
S3_PREFIX="evidence/aws-load-tests"
EVIDENCE_ROOT=""
EXPECTED_ACCOUNT_ID=""
REGION=""
DATA_FILE=""
DRY_RUN=0
SKIP_GRAFANA=0
GRAFANA_URL="${GRAFANA_URL:-}"
GRAFANA_EVIDENCE_USER="${GRAFANA_EVIDENCE_USER:-}"
GRAFANA_EVIDENCE_PASSWORD="${GRAFANA_EVIDENCE_PASSWORD:-}"
DASHBOARD_UID="aws-load-test-b01"
MONITORING_INSTANCE_ID=""
GRAFANA_LOCAL_PORT="3000"

usage() {
  cat <<'USAGE'
usage: download-aws-evidence.sh --run-id ID --s3-bucket NAME --expected-account-id ID --region REGION [options]

Required:
  --run-id ID
  --s3-bucket NAME
  --expected-account-id ID       12-digit AWS account ID this run is approved to target
  --region REGION

Optional:
  --s3-prefix PREFIX             Default: evidence/aws-load-tests
  --evidence-root PATH           Default: evidence/aws-load-tests/<run-id> under the repo root
  --data-file PATH               A securely-retained local copy of the run's data.json (never
                                  sourced from S3 — see upload-aws-evidence.py's SKIP_FILENAMES).
                                  Required unless --skip-grafana and you don't intend to run
                                  build-evidence-manifest.py yourself afterwards.
  --dry-run                      Print the planned aws s3/ssm commands; download nothing
  --skip-grafana                 Skip export-grafana-evidence.py and build-evidence-manifest.py;
                                  only sync files from S3

Grafana export (skipped with --skip-grafana or if these are omitted):
  --grafana-url URL              Default: $GRAFANA_URL, typically http://127.0.0.1:<port> once
                                  the SSM port-forward tunnel below is up
  --grafana-user NAME            Default: $GRAFANA_EVIDENCE_USER (read-only Evidence Exporter account)
  --grafana-password SECRET      Default: $GRAFANA_EVIDENCE_PASSWORD; never logged
  --dashboard-uid UID            Default: aws-load-test-b01
  --monitoring-instance-id ID    If given, prints the exact SSM port-forward command to reach
                                  this Monitoring EC2's Grafana before continuing
  --grafana-local-port PORT      Default: 3000
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID="$2"; shift 2 ;;
    --s3-bucket) S3_BUCKET="$2"; shift 2 ;;
    --s3-prefix) S3_PREFIX="$2"; shift 2 ;;
    --evidence-root) EVIDENCE_ROOT="$2"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --data-file) DATA_FILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --skip-grafana) SKIP_GRAFANA=1; shift ;;
    --grafana-url) GRAFANA_URL="$2"; shift 2 ;;
    --grafana-user) GRAFANA_EVIDENCE_USER="$2"; shift 2 ;;
    --grafana-password) GRAFANA_EVIDENCE_PASSWORD="$2"; shift 2 ;;
    --dashboard-uid) DASHBOARD_UID="$2"; shift 2 ;;
    --monitoring-instance-id) MONITORING_INSTANCE_ID="$2"; shift 2 ;;
    --grafana-local-port) GRAFANA_LOCAL_PORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for required in RUN_ID S3_BUCKET EXPECTED_ACCOUNT_ID REGION; do
  if [[ -z "${!required}" ]]; then
    echo "--${required,,} is required" >&2
    exit 2
  fi
done
if [[ ! "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "--expected-account-id must be exactly 12 digits" >&2
  exit 2
fi
if [[ -z "$EVIDENCE_ROOT" ]]; then
  EVIDENCE_ROOT="$REPOSITORY_ROOT/evidence/aws-load-tests/$RUN_ID"
fi

run_aws_json() {
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
    return 0
  fi
  if [[ "$observed" != "$EXPECTED_ACCOUNT_ID" ]]; then
    echo "observed AWS account does not match --expected-account-id; refusing to download" >&2
    exit 1
  fi
}

echo "[download] run-id=$RUN_ID evidenceRoot=$EVIDENCE_ROOT"
verify_account

S3_URI="s3://$S3_BUCKET/$S3_PREFIX/$RUN_ID/"
mkdir -p "$EVIDENCE_ROOT"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] aws s3 sync $S3_URI $EVIDENCE_ROOT/ --region $REGION" >&2
else
  aws s3 sync "$S3_URI" "$EVIDENCE_ROOT/" --region "$REGION"
  echo "[download] synced $S3_URI -> $EVIDENCE_ROOT/"
fi

if [[ "$SKIP_GRAFANA" == "1" ]]; then
  echo "[download] --skip-grafana: not running export-grafana-evidence.py or build-evidence-manifest.py"
  exit 0
fi

if [[ -n "$MONITORING_INSTANCE_ID" ]]; then
  cat <<EOF
[download] Grafana is only reachable over SSM Port Forwarding (Plan05 step 1). Run this in
another terminal, then re-run this script once the tunnel is up:

  aws ssm start-session \\
    --target $MONITORING_INSTANCE_ID \\
    --document-name AWS-StartPortForwardingSession \\
    --parameters '{"portNumber":["3000"],"localPortNumber":["$GRAFANA_LOCAL_PORT"]}' \\
    --region $REGION
EOF
fi

if [[ -z "$GRAFANA_URL" || -z "$GRAFANA_EVIDENCE_USER" || -z "$GRAFANA_EVIDENCE_PASSWORD" ]]; then
  echo "[download] --grafana-url/--grafana-user/--grafana-password (or \$GRAFANA_URL/\$GRAFANA_EVIDENCE_USER/\$GRAFANA_EVIDENCE_PASSWORD) not fully supplied; skipping Grafana export" >&2
  echo "[download] evidence downloaded but grafana/dashboard.json, grafana/annotations.json, grafana/queries/ are not yet populated" >&2
  exit 0
fi

grafana_args=(
  --evidence-root "$EVIDENCE_ROOT" --grafana-url "$GRAFANA_URL"
  --user "$GRAFANA_EVIDENCE_USER" --password "$GRAFANA_EVIDENCE_PASSWORD"
  --dashboard-uid "$DASHBOARD_UID" --run-id "$RUN_ID" --region "$REGION"
)
if [[ "$DRY_RUN" == "1" ]]; then
  grafana_args+=(--dry-run)
fi
python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/export-grafana-evidence.py" "${grafana_args[@]}"

if [[ "$DRY_RUN" != "1" ]]; then
  echo "[download] PNG capture is required (D-003-R1) but must be done manually: open each URL in"
  echo "[download] $EVIDENCE_ROOT/grafana/panels/panel-<id>.capture.json's captureUrl over the SSM tunnel"
  echo "[download] above, screenshot just that panel, and save it as the file's expectedPngPath."
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] build-evidence-manifest.py --evidence-root $EVIDENCE_ROOT --run-id $RUN_ID --data-file ${DATA_FILE:-<required>} --compare-s3-bucket $S3_BUCKET --s3-prefix $S3_PREFIX --region $REGION" >&2
  exit 0
fi

if [[ -z "$DATA_FILE" ]]; then
  echo "[download] --data-file not supplied; skipping build-evidence-manifest.py (run it yourself once you have a securely-retained copy of this run's data.json)" >&2
  exit 0
fi

python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/build-evidence-manifest.py" \
  --evidence-root "$EVIDENCE_ROOT" --run-id "$RUN_ID" --data-file "$DATA_FILE" \
  --compare-s3-bucket "$S3_BUCKET" --s3-prefix "$S3_PREFIX" --region "$REGION"
