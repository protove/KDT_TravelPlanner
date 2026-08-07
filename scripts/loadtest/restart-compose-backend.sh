#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${1:?usage: restart-compose-backend.sh <run-dir> [restart|stop-start]}"
MODE="${2:-restart}"
REPOSITORY_ROOT="${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:?COMPOSE_ENV_FILE is required}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:?COMPOSE_PROJECT_NAME is required}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPOSITORY_ROOT/compose.yml}"
EVENT_RECORDER="$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py"

compose=(docker compose --env-file "$COMPOSE_ENV_FILE" --project-name "$COMPOSE_PROJECT_NAME" --file "$COMPOSE_FILE")
record_event() {
  python3 "$EVENT_RECORDER" "$RUN_DIR" "$@"
}

record_event T1 "backend fault injection requested: $MODE"
if [[ "$MODE" == "stop-start" ]]; then
  record_event T2 "backend stop command issued"
  "${compose[@]}" stop backend
  "${compose[@]}" start backend
elif [[ "$MODE" == "restart" ]]; then
  record_event T2 "backend restart command issued"
  "${compose[@]}" restart backend
else
  echo "unsupported restart mode: $MODE" >&2
  exit 2
fi

container_id="$("${compose[@]}" ps -q backend)"
if [[ -z "$container_id" ]]; then
  record_event T5_FAIL "backend container id was not found"
  exit 1
fi

for attempt in $(seq 1 120); do
  health_status="$(docker inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
  if [[ "$health_status" == "healthy" ]]; then
    record_event T5 "backend healthcheck=healthy"
    echo "[restart] backend healthy after approximately $((attempt * 2)) seconds"
    exit 0
  fi
  sleep 2
done

record_event T5_FAIL "backend did not become healthy within 240 seconds"
exit 1
