#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${1:?usage: run-k6-compose-diagnostic.sh <run-dir> <variant> <data-file> <project> <network> <base-url> <replicate> <campaign> [profile-file]>}"
VARIANT="${2:?variant is required}"
DATA_FILE="${3:?data file is required}"
PROJECT_NAME="${4:?project name is required}"
NETWORK_NAME="${5:?network name is required}"
BASE_URL="${6:?base URL is required}"
REPLICATE="${7:?replicate is required}"
CAMPAIGN_ID="${8:?campaign id is required}"
REPOSITORY_ROOT="${REPOSITORY_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
PROFILE_FILE="${9:-$REPOSITORY_ROOT/load-tests/diagnostic-profile.json}"
K6_IMAGE="${K6_IMAGE:-grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755}"
PROMETHEUS_RW_URL="${PROMETHEUS_RW_URL:-http://prometheus:9090/api/v1/write}"
RATE="${RATE:-20}"
PREALLOCATED_VUS="${PREALLOCATED_VUS:-20}"
MAX_VUS="${MAX_VUS:-40}"

case "$VARIANT" in
  refresh-only|read-only|fixed-cardinality-mixed|growing-cardinality-mixed) ;;
  *) echo "unsupported diagnostic variant: $VARIANT" >&2; exit 2 ;;
esac
if [[ "$PROJECT_NAME" != travel-planner-diagnostic-* ]]; then
  echo "refusing non-diagnostic Compose project: $PROJECT_NAME" >&2
  exit 2
fi
if [[ "$K6_IMAGE" != *@sha256:* ]]; then
  echo "K6_IMAGE must include a digest" >&2
  exit 2
fi
for required_path in "$DATA_FILE" "$PROFILE_FILE"; do
  if [[ ! -f "$required_path" ]]; then
    echo "required file does not exist: $required_path" >&2
    exit 2
  fi
done

mkdir -p "$RUN_DIR"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git_sha="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
seed_version="$(python3 - "$DATA_FILE" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("seedVersion", "unknown"))
PY
)"
python3 - "$RUN_DIR/metadata.json" "$CAMPAIGN_ID" "$REPLICATE" "$VARIANT" "$PROJECT_NAME" "$started_at" "$git_sha" "$K6_IMAGE" "$seed_version" "$RATE" <<'PY'
import json
import sys
from pathlib import Path

output, campaign, replicate, variant, project, started, commit_sha, image, seed_version, rate = sys.argv[1:]
Path(output).write_text(json.dumps({
    "campaignId": campaign,
    "replicate": int(replicate),
    "variant": variant,
    "composeProject": project,
    "startedAtUtc": started,
    "environment": "compose-production-like",
    "commitSha": commit_sha,
    "k6Image": image,
    "seedVersion": seed_version,
    "ratePerSecond": int(rate),
    "note": "Compose dependency diagnostic only; not an AWS performance claim.",
}, indent=2) + "\n", encoding="utf-8")
PY

python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_START "diagnostic variant $VARIANT started"
: > "$RUN_DIR/runner-stats.jsonl"
container_name="loadtest-k6-diagnostic-${CAMPAIGN_ID}-${REPLICATE}-${VARIANT//[^A-Za-z0-9_.-]/-}"
set +e
docker run --rm -i --name "$container_name" \
  --network "$NETWORK_NAME" \
  -v "$REPOSITORY_ROOT/load-tests/k6:/scripts:ro" \
  -v "$PROFILE_FILE:/profile/diagnostic-profile.json:ro" \
  -v "$DATA_FILE:/data/credentials.json:ro" \
  -v "$RUN_DIR:/out" \
  -e BASE_URL="$BASE_URL" \
  -e DATA_FILE=/data/credentials.json \
  -e PROFILE_FILE=/profile/diagnostic-profile.json \
  -e DIAGNOSTIC_VARIANT="$VARIANT" \
  -e RUN_ID="${CAMPAIGN_ID}-r${REPLICATE}-${VARIANT}" \
  -e RUN_STARTED_AT="$started_at" \
  -e OUT_DIR=/out \
  -e RATE="$RATE" \
  -e PREALLOCATED_VUS="$PREALLOCATED_VUS" \
  -e MAX_VUS="$MAX_VUS" \
  -e K6_PROMETHEUS_RW_SERVER_URL="$PROMETHEUS_RW_URL" \
  -e K6_PROMETHEUS_RW_TREND_STATS='p(90),p(95),p(99)' \
  -e K6_PROMETHEUS_RW_PUSH_INTERVAL=5s \
  -e K6_PROMETHEUS_RW_TREND_AS_NATIVE_HISTOGRAM=false \
  "$K6_IMAGE" run \
  --out json=/out/raw.json \
  --out experimental-prometheus-rw \
  --summary-export=/out/k6-native-summary.json \
  /scripts/scenarios/dependency-diagnostic.js >"$RUN_DIR/stdout.log" 2>&1 &
k6_pid=$!
while kill -0 "$k6_pid" 2>/dev/null; do
  stats="$(docker stats --no-stream --format '{{json .}}' "$container_name" 2>/dev/null || true)"
  if [[ -n "$stats" ]]; then
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"ts":"%s","docker":%s}\n' "$now" "$stats" >> "$RUN_DIR/runner-stats.jsonl"
  fi
  sleep 5
done
wait "$k6_pid"
k6_status=$?
set -e
cat "$RUN_DIR/stdout.log"
python3 - "$RUN_DIR/run-status.json" "$k6_status" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"k6ExitCode": int(sys.argv[2])}, indent=2) + "\n", encoding="utf-8")
PY
python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_END "k6 exit code $k6_status"
echo "[k6] diagnostic run directory: $RUN_DIR"
exit "$k6_status"
