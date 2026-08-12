#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${1:?usage: run-k6-aws-recovery.sh <run-dir>}"
: "${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
: "${BASE_URL:?BASE_URL is required}"
: "${K6_IMAGE_DIGEST:?K6_IMAGE_DIGEST is required}"
: "${AWS_RECOVERY_PROFILE_FILE:?AWS_RECOVERY_PROFILE_FILE is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${REGION:?REGION is required}"
: "${ENVIRONMENT:?ENVIRONMENT is required}"
: "${RATE:?RATE is required}"
: "${DATA_FILE:?DATA_FILE is required}"
: "${EFFECTIVE_MAX_VUS:?EFFECTIVE_MAX_VUS is required}"

K6_DIR="$REPOSITORY_ROOT/load-tests/k6"
if [[ ! "$K6_IMAGE_DIGEST" =~ @sha256:[0-9a-fA-F]{64}$ ]]; then
  echo "K6_IMAGE_DIGEST must be digest-pinned" >&2
  exit 2
fi
[[ -f "$AWS_RECOVERY_PROFILE_FILE" ]] || { echo "missing Recovery profile: $AWS_RECOVERY_PROFILE_FILE" >&2; exit 2; }
[[ -f "$DATA_FILE" ]] || { echo "missing seeded credential file: $DATA_FILE" >&2; exit 2; }
python3 - "$DATA_FILE" "$EFFECTIVE_MAX_VUS" <<'PY'
import json
import sys
from pathlib import Path

path, required_raw = sys.argv[1:]
required = int(required_raw)
payload = json.loads(Path(path).read_text(encoding="utf-8"))
credentials = payload.get("credentials") if isinstance(payload, dict) else None
if payload.get("seedState") != "complete" or payload.get("fixtureState") != "verified":
    raise SystemExit("seeded credential file must have seedState=complete and fixtureState=verified")
if not isinstance(credentials, list) or len(credentials) < required:
    raise SystemExit("credential capacity is insufficient")
print(f"[k6-recovery] unique credential capacity verified: credentials={len(credentials)} maxVUs={required}")
PY

mkdir -p "$RUN_DIR"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git_sha="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
python3 - "$RUN_DIR/metadata.json" "$RUN_ID" "$started_at" "$git_sha" "$K6_IMAGE_DIGEST" "$RATE" "$REGION" "$ENVIRONMENT" "$AWS_RECOVERY_PROFILE_FILE" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output, run_id, started_at, commit_sha, image, rate, region, environment, profile_path = sys.argv[1:]
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
output_path = Path(output)
metadata = {}
if output_path.exists():
    metadata = json.loads(output_path.read_text(encoding="utf-8"))
metadata.update({
    "runId": run_id,
    "scenarioId": "AWS-RECOVERY",
    "scenario": "recovery-steady",
    "platform": "ec2",
    "startedAtUtc": started_at,
    "target": "sanitized-approved-runtime-input",
    "region": region,
    "environment": environment,
    "commitSha": commit_sha,
    "profileSha256": hashlib.sha256(Path(profile_path).read_bytes()).hexdigest(),
    "k6Image": image,
    "rate": float(rate),
    "warmupSeconds": 180,
    "seedVersion": profile["seedVersion"],
    "requestMixVersion": profile["requestMixVersion"],
    "sloVersion": profile["sloVersion"],
    "profileVersion": profile["profileVersion"],
})
output_path.write_text(json.dumps(metadata, indent=2) + chr(10), encoding="utf-8")
PY

if [[ ! -f "$RUN_DIR/operations.jsonl" ]] || ! grep -q '"event": "RUN_START"' "$RUN_DIR/operations.jsonl"; then
  python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_START "AWS Recovery steady workload started" --actor automation
fi
set +e
container_name="loadtest-aws-recovery-k6-${RUN_ID//[^A-Za-z0-9_.-]/-}"
: > "$RUN_DIR/runner-stats.jsonl"
 # recovery-summary.js writes /out/summary.json via handleSummary.
docker run -i --name "$container_name" \
  --user 0:0 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$K6_DIR:/scripts:ro" \
  -v "$(dirname "$AWS_RECOVERY_PROFILE_FILE"):/profiles:ro" \
  -v "$DATA_FILE:/data/data.json:ro" \
  -v "$RUN_DIR:/out" \
  -e BASE_URL="$BASE_URL" \
  -e AWS_RECOVERY_PROFILE_FILE="/profiles/$(basename "$AWS_RECOVERY_PROFILE_FILE")" \
  -e DATA_FILE=/data/data.json \
  -e K6_IMAGE_DIGEST="$K6_IMAGE_DIGEST" \
  -e RATE="$RATE" \
  -e RUN_ID="$RUN_ID" \
  -e RUN_STARTED_AT="$started_at" \
  -e OUT_DIR=/out \
  -e REQUIRED_UNIQUE_CREDENTIAL_COUNT="$EFFECTIVE_MAX_VUS" \
  -e REQUIRE_UNIQUE_CREDENTIALS=1 \
  -e PREALLOCATED_VUS="${PREALLOCATED_VUS:-20}" \
  -e MAX_VUS="${MAX_VUS:-}" \
  -e WARMUP="${WARMUP:-3m}" \
  -e DURATION="${DURATION:-20m}" \
  "$K6_IMAGE_DIGEST" run \
  --out json=/out/raw.json \
  --summary-export=/out/k6-native-summary.json \
  "/scripts/aws/scenarios/recovery-steady.js" >"$RUN_DIR/stdout.log" 2>&1 &
k6_pid=$!
while kill -0 "$k6_pid" 2>/dev/null; do
  stats="$(docker stats --no-stream --format '{{json .}}' "$container_name" 2>/dev/null || true)"
  if [[ -n "$stats" ]]; then
    python3 - "$RUN_DIR/runner-stats.jsonl" "$stats" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path, stats_raw = sys.argv[1:]
try:
    docker_stats = json.loads(stats_raw)
except json.JSONDecodeError:
    raise SystemExit(0)
with Path(path).open("a", encoding="utf-8") as output:
    output.write(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "docker": docker_stats,
    }) + chr(10))
PY
  fi
  sleep 5
done
wait "$k6_pid"
k6_status=$?
set -e
cat "$RUN_DIR/stdout.log"

oom_killed="false"
restart_count="0"
inspect_json="$(docker inspect "$container_name" 2>/dev/null || true)"
if [[ -n "$inspect_json" ]]; then
  oom_killed="$(echo "$inspect_json" | python3 -c "import json,sys; print(str(json.load(sys.stdin)[0]['State'].get('OOMKilled', False)).lower())" 2>/dev/null || echo false)"
  restart_count="$(echo "$inspect_json" | python3 -c "import json,sys; print(json.load(sys.stdin)[0].get('RestartCount', 0))" 2>/dev/null || echo 0)"
fi
docker rm -f "$container_name" >/dev/null 2>&1 || true
python3 - "$RUN_DIR/run-status.json" "$k6_status" "$oom_killed" "$restart_count" <<'PY'
import json
import sys
from pathlib import Path

output, code, oom, restart = sys.argv[1:]
Path(output).write_text(json.dumps({
    "k6ExitCode": int(code),
    "k6ContainerOomKilled": oom == "true",
    "k6ContainerRestartCount": int(restart),
}, indent=2) + chr(10), encoding="utf-8")
PY
python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_END "AWS Recovery k6 exit code $k6_status" --actor automation
python3 - "$RUN_DIR/metadata.json" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
metadata = json.loads(path.read_text(encoding="utf-8"))
metadata["endedAtUtc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
path.write_text(json.dumps(metadata, indent=2) + chr(10), encoding="utf-8")
PY
echo "[k6-recovery] run directory: $RUN_DIR"
exit "$k6_status"
