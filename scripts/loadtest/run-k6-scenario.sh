#!/usr/bin/env bash
set -euo pipefail

SCENARIO="${1:?usage: run-k6-scenario.sh <smoke|baseline|recovery-steady> <run-dir>}"
RUN_DIR="${2:?usage: run-k6-scenario.sh <scenario> <run-dir>}"
REPOSITORY_ROOT="${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
K6_DIR="$REPOSITORY_ROOT/load-tests/k6"
BASE_URL="${K6_TARGET:?K6_TARGET is required}"
K6_IMAGE="${K6_IMAGE:-grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
RATE="${RATE:-8}"
DATA_FILE="$K6_DIR/data/data.json"

case "$SCENARIO" in
  smoke|baseline|recovery-steady) ;;
  *) echo "unsupported k6 scenario: $SCENARIO" >&2; exit 2 ;;
esac
if [[ "$K6_IMAGE" != *@sha256:* ]]; then
  echo "K6_IMAGE must include a digest: $K6_IMAGE" >&2
  exit 2
fi
if [[ ! -f "$DATA_FILE" ]]; then
  echo "missing generated credential file: $DATA_FILE" >&2
  exit 2
fi

mkdir -p "$RUN_DIR"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
seed_version="$(python3 - "$DATA_FILE" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("seedVersion", "unknown"))
PY
)"
git_sha="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
python3 - "$RUN_DIR/metadata.json" "$RUN_ID" "$SCENARIO" "$started_at" "$BASE_URL" "$git_sha" "$K6_IMAGE" "$RATE" "$seed_version" "${COMPOSE_PROJECT_NAME:-unknown}" <<'PY'
import json
import sys
from pathlib import Path

output, run_id, scenario, started_at, target, commit_sha, image, rate, seed_version, project = sys.argv[1:]
Path(output).write_text(json.dumps({
    "runId": run_id,
    "scenario": scenario,
    "startedAtUtc": started_at,
    "target": target,
    "environment": "compose-production-like",
    "commitSha": commit_sha,
    "k6Image": image,
    "rate": int(rate),
    "seedVersion": seed_version,
    "composeProject": project,
    "sloVersion": "v0.1-draft",
    "note": "Compose rehearsal only; not an AWS performance claim.",
}, indent=2) + "\n", encoding="utf-8")
PY

python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_START "k6 scenario $SCENARIO started"
set +e
docker run --rm -i \
  -v "$K6_DIR:/scripts:ro" \
  -v "$RUN_DIR:/out" \
  -e BASE_URL="$BASE_URL" \
  -e RATE="$RATE" \
  -e RUN_ID="$RUN_ID" \
  -e RUN_STARTED_AT="$started_at" \
  -e DATA_FILE=/scripts/data/data.json \
  -e TOKEN_MODE="${TOKEN_MODE:-refresh}" \
  -e OUT_DIR=/out \
  -e DURATION="${DURATION:-}" \
  -e WARMUP="${WARMUP:-}" \
  -e PREALLOCATED_VUS="${PREALLOCATED_VUS:-20}" \
  -e MAX_VUS="${MAX_VUS:-20}" \
  --add-host=host.docker.internal:host-gateway \
  "$K6_IMAGE" run \
  --out json=/out/raw.json \
  --summary-export=/out/k6-native-summary.json \
  "/scripts/scenarios/$SCENARIO.js" | tee "$RUN_DIR/stdout.log"
k6_status=${PIPESTATUS[0]}
set -e

python3 - "$RUN_DIR/run-status.json" "$k6_status" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"k6ExitCode": int(sys.argv[2])}, indent=2) + "\n", encoding="utf-8")
PY
python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_END "k6 exit code $k6_status"
echo "[k6] $SCENARIO run directory: $RUN_DIR"

if [[ "$k6_status" -ne 0 && "${ALLOW_K6_FAILURE:-0}" != "1" ]]; then
  exit "$k6_status"
fi
