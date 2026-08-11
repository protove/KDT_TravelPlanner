#!/usr/bin/env bash
# AWS counterpart to ../run-k6-scenario.sh. Runs one AWS k6 scenario
# (smoke|ramp|baseline|spike) against a real ALB target instead of a Compose
# stack, and writes the same evidence shape (metadata.json, raw.json,
# summary.json, k6-native-summary.json, runner-stats.jsonl, run-status.json,
# operations.jsonl) into RUN_DIR so run-aws-b01.sh/validate-aws-run.py can
# read it the same way summarize-gate.py reads Compose run directories.
#
# Unlike the Compose script, this does not manage any docker compose
# lifecycle (the AWS target is already running) and does not need
# --add-host=host.docker.internal (BASE_URL is a real HTTPS ALB origin, not a
# host-local port). The Runner EC2 only has Docker installed (see
# infra/modules/load_test_runner/templates/runner-user-data.sh.tftpl), so k6
# itself still runs via `docker run` with the digest-pinned image, matching
# the pattern already established by seed-aws-load-data.py/cleanup-aws-load-data.py.
set -euo pipefail

SCENARIO="${1:?usage: run-k6-aws-scenario.sh <smoke|ramp|baseline|spike> <run-dir>}"
RUN_DIR="${2:?usage: run-k6-aws-scenario.sh <scenario> <run-dir>}"
REPOSITORY_ROOT="${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
K6_DIR="$REPOSITORY_ROOT/load-tests/k6"
BASE_URL="${BASE_URL:?BASE_URL is required (approved ALB HTTPS origin)}"
K6_IMAGE_DIGEST="${K6_IMAGE_DIGEST:?K6_IMAGE_DIGEST is required (digest-pinned k6 image)}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
AWS_PROFILE_FILE="${AWS_PROFILE_FILE:?AWS_PROFILE_FILE is required}"
DATA_FILE="${DATA_FILE:?DATA_FILE is required (seeded credential file for this run)}"
REGION="${REGION:?REGION is required}"
ENVIRONMENT="${ENVIRONMENT:?ENVIRONMENT is required}"
EFFECTIVE_MAX_VUS="${EFFECTIVE_MAX_VUS:?EFFECTIVE_MAX_VUS is required}"

declare -A SCENARIO_FILES=(
  [smoke]="smoke.js"
  [ramp]="b01-ramp.js"
  [baseline]="b01-baseline.js"
  [spike]="b01-spike.js"
)
SCENARIO_FILE="${SCENARIO_FILES[$SCENARIO]:-}"
if [[ -z "$SCENARIO_FILE" ]]; then
  echo "unsupported AWS k6 scenario: $SCENARIO" >&2
  exit 2
fi
if [[ "$K6_IMAGE_DIGEST" != *@sha256:* ]]; then
  echo "K6_IMAGE_DIGEST must include a digest: $K6_IMAGE_DIGEST" >&2
  exit 2
fi
if [[ ! -f "$AWS_PROFILE_FILE" ]]; then
  echo "missing AWS profile file: $AWS_PROFILE_FILE" >&2
  exit 2
fi
if [[ ! -f "$DATA_FILE" ]]; then
  echo "missing generated credential file: $DATA_FILE" >&2
  exit 2
fi
python3 - "$DATA_FILE" "$EFFECTIVE_MAX_VUS" <<'PY'
import json
import sys
from pathlib import Path

data_file, required_raw = sys.argv[1:]
try:
    required = int(required_raw)
except ValueError:
    raise SystemExit("EFFECTIVE_MAX_VUS must be a positive integer")
if required < 1 or str(required) != required_raw:
    raise SystemExit("EFFECTIVE_MAX_VUS must be a positive integer")
try:
    payload = json.loads(Path(data_file).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit("generated credential file is not valid readable JSON")
credentials = payload.get("credentials") if isinstance(payload, dict) else None
if not isinstance(credentials, list) or len(credentials) < required:
    observed = len(credentials) if isinstance(credentials, list) else 0
    raise SystemExit(
        f"seeded credential count {observed} is smaller than effective maxVUs {required}; "
        "AWS VUs may not share refresh credentials"
    )
print(f"[k6-aws] unique credential capacity verified: credentials={len(credentials)} maxVUs={required}")
PY

mkdir -p "$RUN_DIR"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git_sha="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
warmup_seconds=0
if [[ "$SCENARIO" == "baseline" ]]; then
  warmup_value="${WARMUP:-3m}"
  if [[ "$warmup_value" =~ ^([0-9]+)m$ ]]; then
    warmup_seconds="$((BASH_REMATCH[1] * 60))"
  elif [[ "$warmup_value" =~ ^([0-9]+)s$ ]]; then
    warmup_seconds="${BASH_REMATCH[1]}"
  else
    echo "WARMUP must be a whole-minute or whole-second value, e.g. 3m or 90s" >&2
    exit 2
  fi
fi
python3 - "$RUN_DIR/metadata.json" "$RUN_ID" "$SCENARIO" "$started_at" "$BASE_URL" "$git_sha" \
  "$K6_IMAGE_DIGEST" "${RATE:-0}" "$REGION" "$ENVIRONMENT" "$warmup_seconds" "$AWS_PROFILE_FILE" <<'PY'
import json
import sys
from pathlib import Path

(output, run_id, scenario, started_at, target, commit_sha, image, rate, region,
 environment, warmup_seconds, profile_path) = sys.argv[1:]
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
Path(output).write_text(json.dumps({
    "runId": run_id,
    "scenario": scenario,
    "startedAtUtc": started_at,
    "target": target,
    "platform": "ec2",
    "region": region,
    "environment": environment,
    "commitSha": commit_sha,
    "k6Image": image,
    "rate": float(rate) if float(rate) else None,
    "warmupSeconds": int(warmup_seconds),
    "seedVersion": profile.get("seedVersion", "unknown"),
    "requestMixVersion": profile.get("requestMixVersion", "unknown"),
    "sloVersion": profile.get("sloVersion", "unknown"),
    "profileVersion": profile.get("profileVersion", "unknown"),
}, indent=2) + "\n", encoding="utf-8")
PY

python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_START "AWS k6 scenario $SCENARIO started" --actor automation
set +e
K6_CONTAINER_NAME="loadtest-aws-k6-${RUN_ID//[^A-Za-z0-9_.-]/-}"
: > "$RUN_DIR/runner-stats.jsonl"
# No --rm here (unlike ../run-k6-scenario.sh's Compose equivalent): the
# container must still exist after it exits so `docker inspect` below can
# read OOMKilled/RestartCount for the Runner-bottleneck-vs-SUT-bottleneck
# distinction D-001-R1 asks for (aws-load-test-handoff/decisions/DECISION_LOG.md).
# It is removed explicitly further down instead.
# The Runner invokes this script as root and deliberately keeps the seeded
# credential file at 0600. The pinned k6 image defaults to uid/gid 12345, so
# it cannot read that bind mount (or write the root-owned evidence directory)
# unless the container uses the Runner's root identity. Keep the credential
# mode private instead of chmod/chowning it for the image user, and remove all
# Linux capabilities plus privilege escalation from the root container. It
# receives no Docker socket and can write only the evidence bind mount.
docker run -i --name "$K6_CONTAINER_NAME" \
  --user 0:0 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$K6_DIR:/scripts:ro" \
  -v "$(dirname "$AWS_PROFILE_FILE"):/profiles:ro" \
  -v "$DATA_FILE:/data/data.json:ro" \
  -v "$RUN_DIR:/out" \
  -e BASE_URL="$BASE_URL" \
  -e AWS_PROFILE_FILE="/profiles/$(basename "$AWS_PROFILE_FILE")" \
  -e DATA_FILE=/data/data.json \
  -e REQUIRE_UNIQUE_CREDENTIALS=1 \
  -e REQUIRED_UNIQUE_CREDENTIAL_COUNT="$EFFECTIVE_MAX_VUS" \
  -e K6_IMAGE_DIGEST="$K6_IMAGE_DIGEST" \
  -e RATE="${RATE:-}" \
  -e START_RATE="${START_RATE:-}" \
  -e RUN_ID="$RUN_ID" \
  -e RUN_STARTED_AT="$started_at" \
  -e OUT_DIR=/out \
  -e DURATION="${DURATION:-}" \
  -e WARMUP="${WARMUP:-}" \
  -e PREALLOCATED_VUS="${PREALLOCATED_VUS:-20}" \
  -e MAX_VUS="${MAX_VUS:-}" \
  -e SPIKE_PEAK_MULTIPLIER="${SPIKE_PEAK_MULTIPLIER:-}" \
  -e SPIKE_HOLD="${SPIKE_HOLD:-}" \
  "$K6_IMAGE_DIGEST" run \
  --out json=/out/raw.json \
  --summary-export=/out/k6-native-summary.json \
  "/scripts/aws/scenarios/$SCENARIO_FILE" >"$RUN_DIR/stdout.log" 2>&1 &
k6_pid=$!
while kill -0 "$k6_pid" 2>/dev/null; do
  stats="$(docker stats --no-stream --format '{{json .}}' "$K6_CONTAINER_NAME" 2>/dev/null || true)"
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

oom_killed="false"
restart_count="0"
inspect_json="$(docker inspect "$K6_CONTAINER_NAME" 2>/dev/null || true)"
if [[ -n "$inspect_json" ]]; then
  oom_killed="$(echo "$inspect_json" | python3 -c "import json,sys; print(str(json.load(sys.stdin)[0]['State'].get('OOMKilled', False)).lower())" 2>/dev/null || echo "false")"
  restart_count="$(echo "$inspect_json" | python3 -c "import json,sys; print(json.load(sys.stdin)[0].get('RestartCount', 0))" 2>/dev/null || echo "0")"
fi
docker rm -f "$K6_CONTAINER_NAME" >/dev/null 2>&1 || true

python3 - "$RUN_DIR/run-status.json" "$k6_status" "$oom_killed" "$restart_count" <<'PY'
import json
import sys
from pathlib import Path
output, k6_status, oom_killed, restart_count = sys.argv[1:]
Path(output).write_text(json.dumps({
    "k6ExitCode": int(k6_status),
    "k6ContainerOomKilled": oom_killed == "true",
    "k6ContainerRestartCount": int(restart_count),
}, indent=2) + "\n", encoding="utf-8")
PY
python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_END "AWS k6 exit code $k6_status" --actor automation
echo "[k6-aws] $SCENARIO run directory: $RUN_DIR"

if [[ "$k6_status" -ne 0 && "${ALLOW_K6_FAILURE:-0}" != "1" ]]; then
  exit "$k6_status"
fi
