#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-all}"
if [[ "$#" -gt 0 ]]; then shift; fi
REPOSITORY_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$REPOSITORY_ROOT/.env.prod.example"
COMPOSE_FILES=("$REPOSITORY_ROOT/compose.yml")
WITH_MONITORING=0
USERS=20
RATE=8
BASELINE_DURATION="${BASELINE_DURATION:-10m}"
RECOVERY_DURATION="${RECOVERY_DURATION:-16m}"
WARMUP="${WARMUP:-3m}"
DRILL_AT_MIN="${DRILL_AT_MIN:-8}"
DRILL_MODE="${DRILL_MODE:-stop-start}"
SPIKE_PEAK_RATE="${SPIKE_PEAK_RATE:-24}"
SPIKE_HOLD="${SPIKE_HOLD:-1m}"
BACKEND_PORT="${BACKEND_PORT:-18080}"
KEEP_STACK="${KEEP_REHEARSAL_STACK:-0}"
PROJECT_OVERRIDE=""
RUN_ID_OVERRIDE=""
K6_IMAGE="${K6_IMAGE:-grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755}"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --compose-file) COMPOSE_FILES=("$2"); shift 2 ;;
    --with-monitoring) WITH_MONITORING=1; shift ;;
    --project-name) PROJECT_OVERRIDE="$2"; shift 2 ;;
    --run-id) RUN_ID_OVERRIDE="$2"; shift 2 ;;
    --users) USERS="$2"; shift 2 ;;
    --rate) RATE="$2"; shift 2 ;;
    --baseline-duration) BASELINE_DURATION="$2"; shift 2 ;;
    --recovery-duration) RECOVERY_DURATION="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --drill-at-min) DRILL_AT_MIN="$2"; shift 2 ;;
    --drill-mode) DRILL_MODE="$2"; shift 2 ;;
    --spike-peak-rate) SPIKE_PEAK_RATE="$2"; shift 2 ;;
    --spike-hold) SPIKE_HOLD="$2"; shift 2 ;;
    --backend-port) BACKEND_PORT="$2"; shift 2 ;;
    --keep-stack) KEEP_STACK=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$MODE" in
  all|smoke|baseline|recovery|spike) ;;
  *) echo "usage: run-compose-rehearsal.sh [all|smoke|baseline|recovery|spike] [options]" >&2; exit 2 ;;
esac

ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd)/$(basename "$ENV_FILE")"
for index in "${!COMPOSE_FILES[@]}"; do
  COMPOSE_FILES[$index]="$(cd "$(dirname "${COMPOSE_FILES[$index]}")" && pwd)/$(basename "${COMPOSE_FILES[$index]}")"
done
if [[ "$WITH_MONITORING" == "1" ]]; then
  COMPOSE_FILES+=("$REPOSITORY_ROOT/compose.monitoring.yml" "$REPOSITORY_ROOT/compose.monitoring.dev.yml")
fi
for compose_file in "${COMPOSE_FILES[@]}"; do
  if [[ ! -f "$compose_file" ]]; then
    echo "compose file does not exist: $compose_file" >&2
    exit 2
  fi
done
if [[ ! -f "$ENV_FILE" ]]; then
  echo "env-file does not exist: $ENV_FILE" >&2
  exit 2
fi
if [[ ! "$USERS" =~ ^[1-9][0-9]*$ || "$USERS" -gt 200 ]]; then
  echo "--users must be between 1 and 200" >&2
  exit 2
fi
if [[ ! "$RATE" =~ ^[1-9][0-9]*$ ]]; then
  echo "--rate must be a positive integer" >&2
  exit 2
fi

python3 "$REPOSITORY_ROOT/scripts/loadtest/validate-rehearsal-config.py" \
  --mode "$MODE" \
  --warmup "$WARMUP" \
  --baseline "$BASELINE_DURATION" \
  --recovery "$RECOVERY_DURATION" \
  --drill-at-min "$DRILL_AT_MIN"

if [[ "$DRILL_MODE" != "stop-start" && "$DRILL_MODE" != "restart" ]]; then
  echo "--drill-mode must be stop-start or restart" >&2
  exit 2
fi
if [[ ! "$SPIKE_PEAK_RATE" =~ ^[1-9][0-9]*$ || "$SPIKE_PEAK_RATE" -lt "$RATE" ]]; then
  echo "--spike-peak-rate must be an integer greater than or equal to --rate" >&2
  exit 2
fi

RUN_ID="${RUN_ID_OVERRIDE:-$(date -u +%Y%m%d-%H%M%S)-$$}"
BASE_RUN_ID="$RUN_ID"
PROJECT_NAME="${PROJECT_OVERRIDE:-travel-planner-rehearsal-$RUN_ID}"
if [[ "$PROJECT_NAME" != travel-planner-rehearsal-* && "${ALLOW_NON_REHEARSAL_PROJECT:-0}" != "1" ]]; then
  echo "refusing non-rehearsal Compose project: $PROJECT_NAME" >&2
  exit 2
fi
EVIDENCE_ROOT="$REPOSITORY_ROOT/evidence/load-tests"
DATA_FILE="$REPOSITORY_ROOT/load-tests/k6/data/data.json"
BASE_URL="http://127.0.0.1:$BACKEND_PORT"
K6_TARGET="http://host.docker.internal:$BACKEND_PORT"
compose=(docker compose --env-file "$ENV_FILE" --project-name "$PROJECT_NAME")
for compose_file in "${COMPOSE_FILES[@]}"; do
  compose+=(--file "$compose_file")
done
COMPOSE_FILES_ENV="$(IFS=:; printf '%s' "${COMPOSE_FILES[*]}")"

export REPOSITORY_ROOT COMPOSE_ENV_FILE="$ENV_FILE" COMPOSE_FILE="${COMPOSE_FILES[0]}" COMPOSE_FILE_LIST="$COMPOSE_FILES_ENV" COMPOSE_PROJECT_NAME="$PROJECT_NAME"
export BACKEND_PORT WARMUP DRILL_MODE
export BASE_URL K6_TARGET RATE K6_IMAGE DATA_FILE SPIKE_PEAK_RATE SPIKE_HOLD
export PREALLOCATED_VUS="$USERS" MAX_VUS="$USERS"
mkdir -p "$EVIDENCE_ROOT"

cleanup() {
  if [[ "$KEEP_STACK" != "1" ]]; then
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  else
    echo "[compose] stack retained: $PROJECT_NAME"
  fi
}
trap cleanup EXIT INT TERM

echo "[compose] project=$PROJECT_NAME backend=$BASE_URL"
"${compose[@]}" config --quiet
services=(backend postgres redis)
if [[ "$WITH_MONITORING" == "1" ]]; then
  services+=(prometheus loki alloy grafana)
fi
"${compose[@]}" up --build --detach --wait "${services[@]}"
curl --fail --silent --show-error "$BASE_URL/api/ping" >/dev/null

seed_phase() {
  local phase="$1"
  local -a seed_args=(
    --users "$USERS"
    --env-file "$ENV_FILE"
    --project-name "$PROJECT_NAME"
    --base-url "$BASE_URL"
    --data-file "$DATA_FILE"
    --seed-tag "$RUN_ID-$phase"
  )
  for compose_file in "${COMPOSE_FILES[@]}"; do
    seed_args+=(--compose-file "$compose_file")
  done
  python3 "$REPOSITORY_ROOT/scripts/loadtest/seed-compose-load-data.py" \
    "${seed_args[@]}"
}

run_scenario() {
  local scenario="$1"
  local suffix="$2"
  local duration="${3:-}"
  local run_dir="$EVIDENCE_ROOT/${BASE_RUN_ID}-${suffix}-${scenario}"
  if [[ -n "$duration" ]]; then export DURATION="$duration"; else unset DURATION || true; fi
  export RUN_ID="${BASE_RUN_ID}-${suffix}"
  ALLOW_K6_FAILURE=0 "$REPOSITORY_ROOT/scripts/loadtest/run-k6-scenario.sh" "$scenario" "$run_dir"
  unset DURATION || true
  echo "$run_dir"
}

run_recovery() {
  local run_dir="$EVIDENCE_ROOT/${BASE_RUN_ID}-recovery-recovery-steady"
  export DURATION="$RECOVERY_DURATION"
  export RUN_ID="${BASE_RUN_ID}-recovery"
  ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/run-k6-scenario.sh" recovery-steady "$run_dir" &
  local k6_pid=$!
  for _ in $(seq 1 100); do
    if [[ -s "$run_dir/operations.jsonl" ]] && rg -q '"event": "RUN_START"' "$run_dir/operations.jsonl"; then
      break
    fi
    sleep 0.1
  done
  if [[ ! -s "$run_dir/operations.jsonl" ]] || ! rg -q '"event": "RUN_START"' "$run_dir/operations.jsonl"; then
    echo "[compose] k6 RUN_START was not recorded" >&2
    kill "$k6_pid" 2>/dev/null || true
    wait "$k6_pid" || true
    return 2
  fi
  target_epoch="$(python3 - "$run_dir/operations.jsonl" "$DRILL_AT_MIN" <<'PY'
import json
import sys
from datetime import datetime

with open(sys.argv[1], encoding="utf-8") as source:
    event = next(json.loads(line) for line in source if json.loads(line)["event"] == "RUN_START")
started = datetime.fromisoformat(event["ts"].replace("Z", "+00:00")).timestamp()
print(started + int(sys.argv[2]) * 60)
PY
)"
  while python3 - "$target_epoch" <<'PY'
import sys
import time
raise SystemExit(0 if time.time() < float(sys.argv[1]) else 1)
PY
  do
    sleep 0.2
  done
  local restart_status=0
  "$REPOSITORY_ROOT/scripts/loadtest/restart-compose-backend.sh" "$run_dir" "$DRILL_MODE" || restart_status=$?
  wait "$k6_pid" || true
  unset DURATION || true
  python3 "$REPOSITORY_ROOT/scripts/loadtest/derive-rehearsal-events.py" "$run_dir" || true
  local warmup_seconds
  if [[ "$WARMUP" =~ ^([0-9]+)m$ ]]; then
    warmup_seconds="$((BASH_REMATCH[1] * 60))"
  else
    echo "--warmup must use a whole-minute value such as 3m" >&2
    return 2
  fi
  local verdict_status=0
  python3 "$REPOSITORY_ROOT/scripts/loadtest/evaluate-recovery.py" "$run_dir" \
    --warmup-sec "$warmup_seconds" --recovery-event T4 || verdict_status=$?
  if [[ "$restart_status" -ne 0 ]]; then
    return "$restart_status"
  fi
  if [[ "$verdict_status" -ne 0 ]]; then
    return "$verdict_status"
  fi
  echo "$run_dir"
}

case "$MODE" in
  smoke)
    seed_phase smoke
    run_scenario smoke smoke
    ;;
  baseline)
    seed_phase baseline
    run_scenario baseline baseline "$BASELINE_DURATION"
    ;;
  recovery)
    seed_phase recovery
    run_recovery
    ;;
  spike)
    seed_phase spike
    run_scenario spike spike
    ;;
  all)
    seed_phase smoke
    run_scenario smoke smoke
    seed_phase baseline
    run_scenario baseline baseline "$BASELINE_DURATION"
    seed_phase recovery
    run_recovery
    ;;
esac

echo "[compose] rehearsal complete; evidence root=$EVIDENCE_ROOT"
