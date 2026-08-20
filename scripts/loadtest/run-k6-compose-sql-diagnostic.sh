#!/usr/bin/env bash
set -euo pipefail

STAGE_DIR="${1:?usage: run-k6-compose-sql-diagnostic.sh <stage-dir> <mode> <item-count> <data-file> <project> <network> <base-url> <replicate> <campaign> [profile]>}"
MODE="${2:?mode is required}"
ITEM_COUNT="${3:?item count is required}"
DATA_FILE="${4:?data file is required}"
PROJECT_NAME="${5:?project is required}"
NETWORK_NAME="${6:?network is required}"
BASE_URL="${7:?base URL is required}"
REPLICATE="${8:?replicate is required}"
CAMPAIGN_ID="${9:?campaign is required}"
ROOT_DIR="${REPOSITORY_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
PROFILE_FILE="${10:-$ROOT_DIR/load-tests/sql-diagnostic-profile.json}"
K6_IMAGE="${K6_IMAGE:-grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755}"
PROMETHEUS_RW_URL="${PROMETHEUS_RW_URL:-http://prometheus:9090/api/v1/write}"
ITERATIONS="${SQL_DIAG_ITERATIONS:-30}"
PACING="${SQL_DIAG_PACING_SECONDS:-0.25}"

case "$MODE" in noop|reverse) ;; *) echo "unsupported mode: $MODE" >&2; exit 2 ;; esac
if [[ ! "$ITEM_COUNT" =~ ^(3|10|25|50|100|200)$ ]]; then echo "unsupported item count" >&2; exit 2; fi
if [[ "$PROJECT_NAME" != travel-planner-sql-diagnostic-scrum-41-* ]]; then echo "refusing non-SQL diagnostic project" >&2; exit 2; fi
if [[ "$K6_IMAGE" != *@sha256:* ]]; then echo "K6_IMAGE must include digest" >&2; exit 2; fi
for required in "$DATA_FILE" "$PROFILE_FILE"; do [[ -f "$required" ]] || { echo "missing $required" >&2; exit 2; }; done

mkdir -p "$STAGE_DIR"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git_sha="$(git -C "$ROOT_DIR" rev-parse HEAD)"
python3 - "$STAGE_DIR/metadata.json" "$CAMPAIGN_ID" "$REPLICATE" "$MODE" "$ITEM_COUNT" "$PROJECT_NAME" "$started_at" "$git_sha" "$K6_IMAGE" "$ITERATIONS" "$PACING" <<'PY'
import json, sys
from pathlib import Path
out, campaign, replicate, mode, count, project, started, sha, image, iterations, pacing = sys.argv[1:]
Path(out).write_text(json.dumps({
    "schemaVersion": "scrum41-sql-stage/v1", "campaignId": campaign,
    "replicate": int(replicate), "mode": mode, "itemCount": int(count),
    "composeProject": project, "startedAtUtc": started, "commitSha": sha,
    "k6Image": image, "warmupIterations": 4, "measuredIterations": int(iterations),
    "pacingSeconds": float(pacing), "environment": "compose-production-like",
}, indent=2) + "\n", encoding="utf-8")
PY
python3 "$ROOT_DIR/scripts/loadtest/record-rehearsal-event.py" "$STAGE_DIR" RUN_START "SQL diagnostic $MODE itemCount=$ITEM_COUNT started"
: > "$STAGE_DIR/runner-stats.jsonl"
container_name="loadtest-k6-sql-${CAMPAIGN_ID}-${REPLICATE}-${MODE}-${ITEM_COUNT}"
set +e
docker run --rm -i --name "$container_name" \
  --network "$NETWORK_NAME" \
  -v "$ROOT_DIR/load-tests/k6:/scripts:ro" \
  -v "$PROFILE_FILE:/profile/sql-diagnostic-profile.json:ro" \
  -v "$DATA_FILE:/data/credentials.json:ro" \
  -v "$STAGE_DIR:/out" \
  -e BASE_URL="$BASE_URL" -e DATA_FILE=/data/credentials.json \
  -e RUN_ID="${CAMPAIGN_ID}-r${REPLICATE}-${MODE}-${ITEM_COUNT}" \
  -e RUN_STARTED_AT="$started_at" -e OUT_DIR=/out \
  -e SQL_DIAG_MODE="$MODE" -e SQL_DIAG_ITEM_COUNT="$ITEM_COUNT" \
  -e SQL_DIAG_ITERATIONS="$ITERATIONS" -e SQL_DIAG_PACING_SECONDS="$PACING" \
  -e K6_PROMETHEUS_RW_SERVER_URL="$PROMETHEUS_RW_URL" \
  -e K6_PROMETHEUS_RW_TREND_STATS='p(90),p(95),p(99)' \
  -e K6_PROMETHEUS_RW_PUSH_INTERVAL=5s \
  "$K6_IMAGE" run --out json=/out/raw.json --out experimental-prometheus-rw \
  --summary-export=/out/k6-native-summary.json /scripts/scenarios/sql-round-trip-diagnostic.js \
  >"$STAGE_DIR/stdout.log" 2>&1 &
k6_pid=$!
while kill -0 "$k6_pid" 2>/dev/null; do
  stats="$(docker stats --no-stream --format '{{json .}}' "$container_name" 2>/dev/null || true)"
  if [[ -n "$stats" ]]; then printf '{"ts":"%s","docker":%s}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$stats" >> "$STAGE_DIR/runner-stats.jsonl"; fi
  sleep 2
done
wait "$k6_pid"
k6_status=$?
set -e
cat "$STAGE_DIR/stdout.log"
python3 - "$STAGE_DIR/run-status.json" "$k6_status" "$STAGE_DIR" <<'PY'
import json, sys
from pathlib import Path
out, status, stage = sys.argv[1:]
Path(out).write_text(json.dumps({"k6ExitCode": int(status), "stageDir": stage}, indent=2) + "\n", encoding="utf-8")
PY
python3 "$ROOT_DIR/scripts/loadtest/record-rehearsal-event.py" "$STAGE_DIR" RUN_END "k6 exit code $k6_status"
exit "$k6_status"
