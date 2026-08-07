#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-all}"
if [[ "$#" -gt 0 ]]; then shift; fi
REPOSITORY_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$REPOSITORY_ROOT/.env.prod.example"
COMPOSE_FILE="$REPOSITORY_ROOT/compose.yml"
USERS=20
RATE=8
BASELINE_DURATION="${BASELINE_DURATION:-10m}"
RECOVERY_DURATION="${RECOVERY_DURATION:-16m}"
WARMUP="${WARMUP:-3m}"
DRILL_AT_MIN="${DRILL_AT_MIN:-8}"
BACKEND_PORT="${BACKEND_PORT:-18080}"
KEEP_STACK="${KEEP_REHEARSAL_STACK:-0}"
PROJECT_OVERRIDE=""
K6_IMAGE="${K6_IMAGE:-grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755}"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --compose-file) COMPOSE_FILE="$2"; shift 2 ;;
    --project-name) PROJECT_OVERRIDE="$2"; shift 2 ;;
    --users) USERS="$2"; shift 2 ;;
    --rate) RATE="$2"; shift 2 ;;
    --baseline-duration) BASELINE_DURATION="$2"; shift 2 ;;
    --recovery-duration) RECOVERY_DURATION="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --drill-at-min) DRILL_AT_MIN="$2"; shift 2 ;;
    --backend-port) BACKEND_PORT="$2"; shift 2 ;;
    --keep-stack) KEEP_STACK=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$MODE" in
  all|smoke|baseline|recovery) ;;
  *) echo "usage: run-compose-rehearsal.sh [all|smoke|baseline|recovery] [options]" >&2; exit 2 ;;
esac

ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd)/$(basename "$ENV_FILE")"
COMPOSE_FILE="$(cd "$(dirname "$COMPOSE_FILE")" && pwd)/$(basename "$COMPOSE_FILE")"
if [[ ! -f "$ENV_FILE" || ! -f "$COMPOSE_FILE" ]]; then
  echo "env-file and compose-file must exist" >&2
  exit 2
fi
if [[ ! "$USERS" =~ ^[1-9][0-9]*$ || "$USERS" -gt 200 ]]; then
  echo "--users must be between 1 and 200" >&2
  exit 2
fi

RUN_ID="$(date -u +%Y%m%d-%H%M%S)-$$"
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
compose=(docker compose --env-file "$ENV_FILE" --project-name "$PROJECT_NAME" --file "$COMPOSE_FILE")

export REPOSITORY_ROOT COMPOSE_ENV_FILE="$ENV_FILE" COMPOSE_FILE COMPOSE_PROJECT_NAME="$PROJECT_NAME"
export BACKEND_PORT WARMUP
export BASE_URL K6_TARGET RATE K6_IMAGE DATA_FILE
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
"${compose[@]}" up --build --detach --wait backend postgres redis
curl --fail --silent --show-error "$BASE_URL/api/ping" >/dev/null

seed_phase() {
  local phase="$1"
  python3 "$REPOSITORY_ROOT/scripts/loadtest/seed-compose-load-data.py" \
    --users "$USERS" \
    --env-file "$ENV_FILE" \
    --compose-file "$COMPOSE_FILE" \
    --project-name "$PROJECT_NAME" \
    --base-url "$BASE_URL" \
    --data-file "$DATA_FILE" \
    --seed-tag "$RUN_ID-$phase"
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
  sleep 5
  sleep "$((DRILL_AT_MIN * 60))"
  local restart_status=0
  "$REPOSITORY_ROOT/scripts/loadtest/restart-compose-backend.sh" "$run_dir" restart || restart_status=$?
  wait "$k6_pid" || true
  unset DURATION || true
  local warmup_seconds
  if [[ "$WARMUP" =~ ^([0-9]+)m$ ]]; then
    warmup_seconds="$((BASH_REMATCH[1] * 60))"
  else
    echo "--warmup must use a whole-minute value such as 3m" >&2
    return 2
  fi
  local verdict_status=0
  python3 "$REPOSITORY_ROOT/scripts/loadtest/evaluate-recovery.py" "$run_dir" \
    --warmup-sec "$warmup_seconds" --recovery-event T1 || verdict_status=$?
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
