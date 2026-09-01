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

SCENARIO="${1:?usage: run-k6-aws-scenario.sh <smoke|ramp|baseline|spike|soak|scale-step|capacity-stress> <run-dir>}"
RUN_DIR="${2:?usage: run-k6-aws-scenario.sh <scenario> <run-dir>}"
REPOSITORY_ROOT="${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
K6_DIR="$REPOSITORY_ROOT/load-tests/k6"
CONTRACT_DIR="$REPOSITORY_ROOT/load-tests/aws/contracts"
BASE_URL="${BASE_URL:?BASE_URL is required (approved ALB HTTPS origin)}"
K6_IMAGE_DIGEST="${K6_IMAGE_DIGEST:?K6_IMAGE_DIGEST is required (digest-pinned k6 image)}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
AWS_PROFILE_FILE="${AWS_PROFILE_FILE:?AWS_PROFILE_FILE is required}"
DATA_FILE="${DATA_FILE:?DATA_FILE is required (seeded credential file for this run)}"
REGION="${REGION:?REGION is required}"
ENVIRONMENT="${ENVIRONMENT:?ENVIRONMENT is required}"
TARGET_PLATFORM="${TARGET_PLATFORM:-ec2}"
AWS_SLO_CONTRACT_FILE="${AWS_SLO_CONTRACT_FILE:-$CONTRACT_DIR/slo-v1.1-candidate.json}"
EFFECTIVE_MAX_VUS="${EFFECTIVE_MAX_VUS:?EFFECTIVE_MAX_VUS is required}"
MOCK_CONTAINER_NAME="${MOCK_CONTAINER_NAME:-travel-planner-google-api-mock}"

# A private Runner may resolve the approved custom hostname on the host via an
# operator-provided /etc/hosts entry while Docker's bridge network still asks
# the VPC resolver.  Keep the hostname (and therefore TLS SNI/HTTP Host) as
# the workload target, but allow the operator to pin the current ALB address
# set for this disposable run.  This is deliberately an execution-time input:
# the workload never discovers, changes, or recovers an ALB/DNS record.
DOCKER_HOST_ARGS=()
if [[ -n "${AWS_TARGET_HOST_IPS:-}" ]]; then
  target_host="$(python3 - "$BASE_URL" <<'PY'
import sys
from urllib.parse import urlparse

host = urlparse(sys.argv[1]).hostname
if not host or "." not in host:
    raise SystemExit("BASE_URL hostname is missing")
print(host)
PY
)"
  old_ifs="$IFS"
  IFS=,
  read -r -a target_ips <<< "$AWS_TARGET_HOST_IPS"
  IFS="$old_ifs"
  if [[ "${#target_ips[@]}" -eq 0 ]]; then
    echo "AWS_TARGET_HOST_IPS must contain at least one IPv4 address" >&2
    exit 2
  fi
  for target_ip in "${target_ips[@]}"; do
    if [[ ! "$target_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
      echo "AWS_TARGET_HOST_IPS contains a non-IPv4 value" >&2
      exit 2
    fi
    if ! python3 - "$target_ip" <<'PY'
import ipaddress
import sys

try:
    ipaddress.IPv4Address(sys.argv[1])
except ipaddress.AddressValueError:
    raise SystemExit(1)
PY
    then
      echo "AWS_TARGET_HOST_IPS contains an invalid IPv4 address" >&2
      exit 2
    fi
    DOCKER_HOST_ARGS+=(--add-host "${target_host}:${target_ip}")
  done
fi

if [[ ! -f "$AWS_PROFILE_FILE" ]]; then
  echo "missing AWS profile file: $AWS_PROFILE_FILE" >&2
  exit 2
fi
# Orchestrator callers may pass a repository-relative profile path. Docker
# interprets a relative `-v` source containing `/` as an invalid named volume,
# so normalize the reviewed file before calculating its parent mount.
AWS_PROFILE_FILE="$(cd "$(dirname "$AWS_PROFILE_FILE")" && pwd -P)/$(basename "$AWS_PROFILE_FILE")"
PROFILE_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profileVersion", ""))' "$AWS_PROFILE_FILE")"
case "$SCENARIO" in
  smoke) SCENARIO_FILE="smoke.js" ;;
  ramp) SCENARIO_FILE="b01-ramp.js" ;;
  baseline) SCENARIO_FILE="b01-baseline.js" ;;
  spike) SCENARIO_FILE="b01-spike.js" ;;
  soak) SCENARIO_FILE="soak.js" ;;
  scale-step) SCENARIO_FILE="scale-step.js" ;;
  capacity-stress)
    if [[ "$TARGET_PLATFORM" == "eks" || "$PROFILE_VERSION" == "aws-eks-monolith-breakpoint-v1.0" || "$PROFILE_VERSION" == "aws-eks-monolith-breakpoint-v2.0" || "$PROFILE_VERSION" == "aws-eks-monolith-breakpoint-v2.1" ]]; then
      SCENARIO_FILE="eks-scale-capacity.js"
    else
      SCENARIO_FILE="capacity-stress.js"
    fi
    ;;
  *) SCENARIO_FILE="" ;;
esac
if [[ -z "$SCENARIO_FILE" ]]; then
  echo "unsupported AWS k6 scenario: $SCENARIO" >&2
  exit 2
fi
if [[ "$K6_IMAGE_DIGEST" != *@sha256:* ]]; then
  echo "K6_IMAGE_DIGEST must include a digest: $K6_IMAGE_DIGEST" >&2
  exit 2
fi
if [[ ! -f "$AWS_SLO_CONTRACT_FILE" ]]; then
  echo "missing SLO contract file: $AWS_SLO_CONTRACT_FILE" >&2
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
if not isinstance(payload, dict) or payload.get("seedState") != "complete":
    raise SystemExit("generated credential file seedState must be complete")
if payload.get("fixtureState") != "verified":
    raise SystemExit("generated credential file fixtureState must be verified")
if not isinstance(credentials, list) or len(credentials) < required:
    observed = len(credentials) if isinstance(credentials, list) else 0
    raise SystemExit(
        f"seeded credential count {observed} is smaller than effective maxVUs {required}; "
        "AWS VUs may not share refresh credentials"
    )
print(f"[k6-aws] unique credential capacity verified: credentials={len(credentials)} maxVUs={required}")
PY

mkdir -p "$RUN_DIR"
if [[ "$TARGET_PLATFORM" == "eks" ]]; then
  # The live EKS render must prove the separately isolated Runner mock is
  # healthy before any measured operation is admitted.  A failed preflight is
  # an incomplete run, never an application terminal.
  RUNNER_READINESS_FILE="${RUNNER_READINESS_FILE:-/var/lib/travel-planner/load-test-evidence/runner-readiness.json}"
  [[ -s "$RUNNER_READINESS_FILE" ]] || {
    echo "Runner full-readiness receipt is missing" >&2
    exit 3
  }
  python3 - "$RUNNER_READINESS_FILE" "${RUNNER_BOOTSTRAP_RUN_ID:-$RUN_ID}" "${SOURCE_COMMIT_SHA:-}" "$K6_IMAGE_DIGEST" <<'PY'
import json
import sys
from pathlib import Path

path, run_id, source_sha, k6_image = sys.argv[1:]
payload = json.loads(Path(path).read_text(encoding="utf-8"))
if payload.get("status") != "ready" or payload.get("runId") != run_id:
    raise SystemExit("Runner full-readiness receipt is not ready for this run")
if source_sha and payload.get("sourceCommitSha") != source_sha:
    raise SystemExit("Runner full-readiness source SHA does not match this run")
if payload.get("k6ImageReference") != k6_image:
    raise SystemExit("Runner full-readiness k6 image does not match this run")
mock = payload.get("mock") if isinstance(payload.get("mock"), dict) else {}
if mock.get("healthStatus") != "ok" or int(mock.get("contractRoutesVerified", 0)) < 4:
    raise SystemExit("Runner private mock contract is incomplete")
PY
  if ! curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8080/healthz >/dev/null; then
    echo "Google API mock is not healthy on the Runner" >&2
    exit 3
  fi
fi
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
  "$K6_IMAGE_DIGEST" "${RATE:-0}" "$REGION" "$ENVIRONMENT" "$TARGET_PLATFORM" "$warmup_seconds" "$AWS_PROFILE_FILE" \
  "${AWS_TARGET_HOST_IPS:-}" <<'PY'
import hashlib
import json
import os
import sys
from urllib.parse import urlparse
from pathlib import Path

(output, run_id, scenario, started_at, target, commit_sha, image, rate, region,
 environment, platform, warmup_seconds, profile_path, target_host_ips_raw) = sys.argv[1:]
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
profile_sha256 = hashlib.sha256(Path(profile_path).read_bytes()).hexdigest()
rate_value = float(rate) if float(rate) else None
scenario_profile = profile.get("scenarios", {}).get(scenario, {})
target_host_ips = [value.strip() for value in target_host_ips_raw.split(",") if value.strip()]
effective_inputs = {
    "scenario": scenario,
    "profileSha256": profile_sha256,
    "rate": rate_value,
}
if os.environ.get("CAPACITY_STAGE"):
    effective_inputs["campaignStage"] = os.environ["CAPACITY_STAGE"]
if scenario == "spike":
    baseline_rate = rate_value
    peak_multiplier = float(os.environ.get("SPIKE_PEAK_MULTIPLIER") or scenario_profile.get("peakRateMultiplier"))
    effective_inputs.update({
        "classification": "diagnostic",
        "baselineRate": baseline_rate,
        "peakRateMultiplier": peak_multiplier,
        "peakRate": baseline_rate * peak_multiplier if baseline_rate is not None else None,
        "hold": os.environ.get("SPIKE_HOLD") or scenario_profile.get("hold"),
        "preAllocatedVUs": int(os.environ.get("PREALLOCATED_VUS") or scenario_profile.get("preAllocatedVUs")),
        "maxVUs": int(os.environ.get("MAX_VUS") or scenario_profile.get("maxVUs")),
        "timeUnit": scenario_profile.get("timeUnit", "1s"),
    })
elif scenario == "capacity-stress":
    stress = profile.get("capacityStress") or {}
    adaptive = profile.get("profileVersion") == "aws-eks-monolith-breakpoint-v2.0" or stress.get("adaptive") is True
    base_rate_raw = os.environ.get("CAPACITY_TARGET_RATE") or os.environ.get("CONFIRMED_RATE") or rate
    try:
        base_rate = float(base_rate_raw)
    except (TypeError, ValueError):
        raise SystemExit("capacity-stress requires a positive target rate")
    if base_rate <= 0:
        raise SystemExit("capacity-stress target rate must be positive")
    multipliers = stress.get("stageMultipliers") or scenario_profile.get("stageMultipliers")
    durations = stress.get("stageDurations") or scenario_profile.get("stageDurations")
    campaign_stage = os.environ.get("CAPACITY_STAGE", "")
    if adaptive:
        multipliers = [1]
        durations = [os.environ.get("CAPACITY_STAGE_DURATION") or stress.get("duration") or scenario_profile.get("duration") or "5m"]
    elif campaign_stage == "pod-scale-out":
        multipliers, durations = multipliers[:2], durations[:2]
    elif campaign_stage == "recovery":
        multipliers, durations = [1], ["2m"]
    effective_inputs.update({
        "campaignStage": campaign_stage or "capacity-stress",
        "adaptive": adaptive,
        "targetRate": base_rate if adaptive else None,
        "stageIndex": int(os.environ.get("CAPACITY_STAGE_INDEX") or 0) if adaptive else None,
        "baseRate": base_rate,
        "stageMultipliers": multipliers,
        "stageDurations": durations,
        "stageRates": [base_rate * float(multiplier) for multiplier in multipliers],
        "nominalHoldSeconds": stress.get("nominalHoldSeconds"),
        "conditionalExtensionSeconds": stress.get("conditionalExtensionSeconds"),
        "maxSingleStageSeconds": stress.get("maxSingleStageSeconds"),
        "capacityStabilitySeconds": stress.get("capacityStabilitySeconds"),
        "fixedRpsCeiling": stress.get("fixedRpsCeiling"),
        "maxVUs": int(os.environ.get("MAX_VUS") or stress.get("maxVUs")),
        "preAllocatedVUs": int(os.environ.get("PREALLOCATED_VUS") or stress.get("preAllocatedVUs")),
        "terminalConditions": [
            "NODE_MAX_PENDING", "NODE_SCALE_NOT_TRIGGERED", "NODE_SCALE_FAILED",
            "NODE_COMPUTE_SATURATION", "SLO_COLLAPSE", "THROUGHPUT_PLATEAU",
            "HPA_CAPACITY_EXHAUSTED", "BACKEND_OOM", "BACKEND_UNHEALTHY",
            "ALB_SATURATION", "DATA_TIER_SATURATION",
        ],
        "requiresCompleteSloWindows": stress.get("requiresCompleteSloWindows", False),
        "capacityModel": profile.get("eks", {}).get("capacityMethod"),
        "nodeGroupContract": profile.get("eks", {}).get("nodeGroup"),
        "baseHpaContract": profile.get("eks", {}).get("baseHpa"),
    })
Path(output).write_text(json.dumps({
    "runId": run_id,
    "scenario": scenario,
    "startedAtUtc": started_at,
    "target": target,
    "platform": platform,
    "region": region,
    "environment": environment,
    "commitSha": commit_sha,
    "k6Image": image,
    "rate": rate_value,
    "warmupSeconds": int(warmup_seconds),
    "seedVersion": profile.get("seedVersion", "unknown"),
    "requestMixVersion": profile.get("requestMixVersion", "unknown"),
    "sloVersion": profile.get("sloVersion", "unknown"),
    "profileVersion": profile.get("profileVersion", "unknown"),
    "profileSha256": profile_sha256,
    "targetHostResolution": {
        "hostname": urlparse(target).hostname,
        "ips": target_host_ips,
        "method": "docker-add-host" if target_host_ips else "container-vpc-dns",
    },
    "effectiveInputs": effective_inputs,
}, indent=2) + "\n", encoding="utf-8")
PY

python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_START "AWS k6 scenario $SCENARIO started" --actor automation
set +e
K6_CONTAINER_NAME="loadtest-aws-k6-${RUN_ID//[^A-Za-z0-9_.-]/-}"
: > "$RUN_DIR/runner-stats.jsonl"
: > "$RUN_DIR/mock-stats.jsonl"
slo_producer_pid=""
slo_producer_status=0
# Capacity/scale runs need a live SLO stream while k6 is still executing. A
# summary.json written at process exit cannot drive the observer's terminal
# decision, so the producer tails raw.json and emits complete, non-overlapping
# 60-second windows. The final once/finalize pass closes any window that became
# complete just before k6 exited.
if [[ "$SCENARIO" == "capacity-stress" || "$SCENARIO" == eks-* || ("$SCENARIO" == "baseline" && "$TARGET_PLATFORM" == "eks") ]]; then
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/produce-capacity-slo-windows.py" \
    --input "$RUN_DIR/raw.json" --output "$RUN_DIR/slo-windows.jsonl" \
    --metadata "$RUN_DIR/metadata.json" --slo-contract "$AWS_SLO_CONTRACT_FILE" \
    --poll-seconds "${SLO_WINDOW_POLL_SECONDS:-2}" \
    >"$RUN_DIR/slo-window-producer.log" 2>&1 &
  slo_producer_pid=$!
fi
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
  "${DOCKER_HOST_ARGS[@]}" \
  -v "$K6_DIR:/scripts:ro" \
  -v "$CONTRACT_DIR:/contracts:ro" \
  -v "$(dirname "$AWS_PROFILE_FILE"):/profiles:ro" \
  -v "$DATA_FILE:/data/data.json:ro" \
  -v "$RUN_DIR:/out" \
  -e BASE_URL="$BASE_URL" \
  -e TARGET_REGION="$REGION" \
  -e TARGET_ENVIRONMENT="$ENVIRONMENT" \
  -e AWS_PROFILE_FILE="/profiles/$(basename "$AWS_PROFILE_FILE")" \
  -e AWS_SLO_CONTRACT_FILE="/contracts/$(basename "$AWS_SLO_CONTRACT_FILE")" \
  -e DATA_FILE=/data/data.json \
  -e REQUIRE_UNIQUE_CREDENTIALS=1 \
  -e REQUIRED_UNIQUE_CREDENTIAL_COUNT="$EFFECTIVE_MAX_VUS" \
  -e K6_IMAGE_DIGEST="$K6_IMAGE_DIGEST" \
  -e RATE="${RATE:-}" \
  -e CONFIRMED_RATE="${CONFIRMED_RATE:-}" \
  -e START_RATE="${START_RATE:-}" \
  -e RUN_ID="$RUN_ID" \
  -e RUN_STARTED_AT="$started_at" \
  -e TARGET_PLATFORM="$TARGET_PLATFORM" \
  -e OUT_DIR=/out \
  -e DURATION="${DURATION:-}" \
  -e WARMUP="${WARMUP:-}" \
  -e PREALLOCATED_VUS="${PREALLOCATED_VUS:-20}" \
  -e MAX_VUS="${MAX_VUS:-}" \
  -e CAPACITY_STAGE="${CAPACITY_STAGE:-}" \
  -e CAPACITY_TARGET_RATE="${CAPACITY_TARGET_RATE:-}" \
  -e CAPACITY_STAGE_INDEX="${CAPACITY_STAGE_INDEX:-}" \
  -e CAPACITY_STAGE_DURATION="${CAPACITY_STAGE_DURATION:-}" \
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
  if [[ "$TARGET_PLATFORM" == "eks" ]]; then
    mock_stats="$(docker stats --no-stream --format '{{json .}}' "$MOCK_CONTAINER_NAME" 2>/dev/null || true)"
    if [[ -n "$mock_stats" ]]; then
      now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf '{"ts":"%s","docker":%s}\n' "$now" "$mock_stats" >> "$RUN_DIR/mock-stats.jsonl"
    fi
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

# Seal independent mock/access/error/container evidence while the Runner
# still owns the container and its bind-mounted logs.  The files are bounded
# so a runaway mock request log cannot become an unreviewable evidence blob.
mkdir -p "$RUN_DIR/mock"
mock_inspect="$(docker inspect "$MOCK_CONTAINER_NAME" 2>/dev/null || true)"
if [[ -n "$mock_inspect" ]]; then
  python3 - "$RUN_DIR/mock/container-inspect.json" "$mock_inspect" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
try:
    item = json.loads(sys.argv[2])[0]
except (json.JSONDecodeError, IndexError, TypeError):
    item = {}
state = item.get("State", {}) if isinstance(item, dict) else {}
config = item.get("Config", {}) if isinstance(item, dict) else {}
output.write_text(json.dumps({
    "containerName": item.get("Name", "").lstrip("/") if isinstance(item, dict) else None,
    "image": config.get("Image") if isinstance(config, dict) else None,
    "running": state.get("Running"),
    "status": state.get("Status"),
    "oomKilled": state.get("OOMKilled"),
    "restartCount": item.get("RestartCount", 0) if isinstance(item, dict) else 0,
}, indent=2) + "\n", encoding="utf-8")
PY
  curl_status="$(curl --silent --show-error --max-time 3 -o "$RUN_DIR/mock/healthz.json" -w '%{http_code}' http://127.0.0.1:8080/healthz || true)"
  cp /var/lib/travel-planner/google-api-mock-logs/access.log "$RUN_DIR/mock/access.log" 2>/dev/null || :
  cp /var/lib/travel-planner/google-api-mock-logs/error.log "$RUN_DIR/mock/error.log" 2>/dev/null || :
  tail -c 1048576 "$RUN_DIR/mock/access.log" > "$RUN_DIR/mock/access.log.bounded" 2>/dev/null || :
  tail -c 1048576 "$RUN_DIR/mock/error.log" > "$RUN_DIR/mock/error.log.bounded" 2>/dev/null || :
  python3 - "$RUN_DIR/mock/evidence.json" "$curl_status" "$RUN_DIR/mock/access.log.bounded" "$RUN_DIR/mock/error.log.bounded" "$RUN_DIR/mock/container-inspect.json" "$RUN_DIR/mock-stats.jsonl" <<'PY'
import json
import re
import sys
from pathlib import Path

output, status, access_path, error_path, inspect_path, stats_path = sys.argv[1:]
output = Path(output)
access_path = Path(access_path)
error_path = Path(error_path)
inspect_path = Path(inspect_path)
stats_path = Path(stats_path)
def text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
access = text(access_path)
errors = text(error_path)
inspect = json.loads(text(inspect_path) or "{}")
stats = [json.loads(line) for line in text(stats_path).splitlines() if line.strip()]
stats = [item.get("docker", {}) for item in stats if isinstance(item, dict) and isinstance(item.get("docker"), dict)]
http5xx = sum(1 for line in access.splitlines() if re.search(r'"status":5[0-9][0-9](?:,|})', line))
cpu = []
memory = []
for item in stats:
    for key, target in (("CPUPerc", cpu), ("MemPerc", memory)):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", str(item.get(key, "")))
        if match:
            target.append(float(match.group(1)))
output.write_text(json.dumps({
    "schemaVersion": "google-api-mock-evidence/v1",
    "health": {"httpStatus": int(status) if status.isdigit() else None, "ok": status == "200"},
    "requests": {
        "accessLogLines": len(access.splitlines()),
        "errorLogLines": len(errors.splitlines()),
        "http5xxLines": http5xx,
    },
    "container": inspect,
    "headroom": {
        "maxCpuPercent": max(cpu) if cpu else None,
        "maxMemoryPercent": max(memory) if memory else None,
        "samples": len(stats),
    },
    "validity": "VALID" if status == "200" and inspect.get("running") is True and inspect.get("oomKilled") is not True and int(inspect.get("restartCount", 0) or 0) == 0 and http5xx == 0 else "INCOMPLETE_MOCK_DEPENDENCY",
}, indent=2) + "\n", encoding="utf-8")
PY
else
  printf '%s\n' '{"schemaVersion":"google-api-mock-evidence/v1","validity":"not-required","reason":"non-EKS target"}' > "$RUN_DIR/mock/evidence.json"
fi

if [[ -n "$slo_producer_pid" ]]; then
  if kill -0 "$slo_producer_pid" 2>/dev/null; then
    kill -TERM "$slo_producer_pid" 2>/dev/null || true
  fi
  wait "$slo_producer_pid" 2>/dev/null
  slo_producer_status=$?
  # Background jobs launched by a non-interactive shell inherit SIGINT as an
  # ignored disposition, so kill -INT can leave the producer tailing raw.json
  # forever after k6 exits. SIGTERM is not ignored in that context and is the
  # normal, explicit producer shutdown path. Keep both legacy SIGINT (130) and
  # SIGTERM (143) as successful shutdowns; any other exit remains fail-closed
  # in run-status.json and invalidates complete-window requirements.
  [[ "$slo_producer_status" -eq 130 || "$slo_producer_status" -eq 143 ]] && slo_producer_status=0
  set +e
  python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/produce-capacity-slo-windows.py" \
    --input "$RUN_DIR/raw.json" --output "$RUN_DIR/slo-windows.jsonl" \
    --metadata "$RUN_DIR/metadata.json" --slo-contract "$AWS_SLO_CONTRACT_FILE" \
    --once --finalize
  finalize_status=$?
  if [[ "$finalize_status" -ne 0 && "$slo_producer_status" -eq 0 ]]; then
    slo_producer_status="$finalize_status"
  fi
  set -e
fi

python3 - "$RUN_DIR/run-status.json" "$k6_status" "$oom_killed" "$restart_count" "$slo_producer_status" <<'PY'
import json
import sys
from pathlib import Path
output, k6_status, oom_killed, restart_count, slo_producer_status = sys.argv[1:]
Path(output).write_text(json.dumps({
    "k6ExitCode": int(k6_status),
    "k6ContainerOomKilled": oom_killed == "true",
    "k6ContainerRestartCount": int(restart_count),
    "sloWindowProducerExitCode": int(slo_producer_status),
}, indent=2) + "\n", encoding="utf-8")
PY
python3 "$REPOSITORY_ROOT/scripts/loadtest/record-rehearsal-event.py" "$RUN_DIR" RUN_END "AWS k6 exit code $k6_status" --actor automation
echo "[k6-aws] $SCENARIO run directory: $RUN_DIR"

if [[ "$k6_status" -ne 0 && "${ALLOW_K6_FAILURE:-0}" != "1" ]]; then
  exit "$k6_status"
fi
