#!/usr/bin/env bash
# Run a single named B-01 phase (smoke|ramp|baseline|spike) against the
# already-verified AWS target. This is the AWS analog of
# ../run-compose-rehearsal.sh's per-mode case blocks, minus Compose stack
# lifecycle (the ALB/ASG/Runner are already running) and minus seeding (B-01
# seeds once for the whole run — see orchestrate-aws-b01.sh's "seed" step —
# rather than once per phase like the Compose rehearsal).
#
# Callers (orchestrate-aws-b01.sh) are expected to export every variable this
# script reads below; it does not parse its own --flags so the same
# resolved AWS target/profile/limits are guaranteed to apply to every phase
# of one B-01 run.
set -euo pipefail

PHASE="${1:?usage: run-aws-b01.sh <smoke|ramp|baseline|spike|soak|scale-step|capacity-stress|pod-scale-out|node-scale-out-breakpoint|recovery> [rep]}"
REP="${2:-}"

# The adaptive capacity coordinator sends SIGINT at a clean stage boundary.
# Keep the phase wrapper alive while run-k6-aws-scenario.sh flushes and seals
# its evidence; without this trap the wrapper exits with -SIGINT and the next
# rate can collide with the prior stage's stopped Docker container.
phase_signal_received=0
handle_phase_signal() {
  phase_signal_received=1
}
if [[ "$PHASE" == "capacity-stress" ]]; then
  trap handle_phase_signal INT TERM
fi

: "${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
: "${EVIDENCE_ROOT:?EVIDENCE_ROOT is required}"
: "${BASE_URL:?BASE_URL is required}"
: "${K6_IMAGE_DIGEST:?K6_IMAGE_DIGEST is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${AWS_PROFILE_FILE:?AWS_PROFILE_FILE is required}"
: "${REGION:?REGION is required}"
: "${ENVIRONMENT:?ENVIRONMENT is required}"
TARGET_PLATFORM="${TARGET_PLATFORM:-ec2}"
EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:-}"
EKS_NODE_GROUP_NAME="${EKS_NODE_GROUP_NAME:-}"
EKS_BASTION_ID="${EKS_BASTION_ID:-}"
BACKEND_NAMESPACE="${BACKEND_NAMESPACE:-travel-planner}"
BACKEND_DEPLOYMENT="${BACKEND_DEPLOYMENT:-backend}"
TARGET_GROUP_ARN="${TARGET_GROUP_ARN:-}"
MAX_RATE="${MAX_RATE:-}"
OPERATOR_MAX_VUS="${MAX_VUS:?MAX_VUS is required}"
PROFILE_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profileVersion", ""))' "$AWS_PROFILE_FILE")"
ADAPTIVE_BREAKPOINT="$(python3 -c 'import json,sys; print("1" if json.load(open(sys.argv[1])).get("profileVersion") in {"aws-eks-monolith-breakpoint-v2.0", "aws-eks-monolith-breakpoint-v2.1", "aws-eks-monolith-msa-boundary-v1.0", "aws-eks-monolith-msa-boundary-v1.1"} else "0")' "$AWS_PROFILE_FILE")"
if [[ "$ADAPTIVE_BREAKPOINT" != "1" && -z "$MAX_RATE" ]]; then
  echo "MAX_RATE is required for historical finite AWS profiles" >&2
  exit 2
fi

case "$PHASE" in
  smoke|ramp|baseline|spike|soak|scale-step|capacity-stress|pod-scale-out|node-scale-out-breakpoint|recovery) ;;
  *) echo "usage: run-aws-b01.sh <smoke|ramp|baseline|spike|soak|scale-step|capacity-stress|pod-scale-out|node-scale-out-breakpoint|recovery> [rep]" >&2; exit 2 ;;
esac
if [[ "$PHASE" == "baseline" && -z "$REP" ]]; then
  echo "baseline requires a rep number: run-aws-b01.sh baseline <rep>" >&2
  exit 2
fi

suffix="$PHASE"
[[ -n "$REP" ]] && suffix="$PHASE-$REP"
run_dir="${CAPACITY_STAGE_DIR:-$EVIDENCE_ROOT/k6/$suffix}"
phase_run_id="$RUN_ID-$suffix"

export REPOSITORY_ROOT BASE_URL K6_IMAGE_DIGEST AWS_PROFILE_FILE REGION ENVIRONMENT TARGET_PLATFORM
export AWS_SLO_CONTRACT_FILE="${AWS_SLO_CONTRACT_FILE:-$REPOSITORY_ROOT/load-tests/aws/contracts/slo-v1.1-candidate.json}"
export RUN_ID="$phase_run_id"

configure_phase_max_vus() {
  local phase="$1"
  local override="$2"
  EFFECTIVE_MAX_VUS="$(python3 - "$AWS_PROFILE_FILE" "$phase" "$OPERATOR_MAX_VUS" "$override" <<'PY'
import json
import sys
from pathlib import Path

profile_path, phase, ceiling_raw, override_raw = sys.argv[1:]
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
profile_phase = "capacity-stress" if phase in {"pod-scale-out", "node-scale-out-breakpoint", "recovery"} else phase
scenario = profile.get("scenarios", {}).get(profile_phase, {})
profile_vus = scenario.get("vus") if phase == "smoke" else scenario.get("maxVUs")

def positive_integer(raw, label):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise SystemExit(f"{label} must be a positive integer")
    if value < 1 or str(value) != str(raw):
        raise SystemExit(f"{label} must be a positive integer")
    return value

ceiling = positive_integer(ceiling_raw, "MAX_VUS operator ceiling")
effective = positive_integer(override_raw or profile_vus, f"{phase} maxVUs")
profile_limit = positive_integer(profile.get("limits", {}).get("maxVUs"), "profile limits.maxVUs")
if effective > profile_limit:
    raise SystemExit(f"{phase} maxVUs {effective} exceeds profile limits.maxVUs {profile_limit}")
if effective > ceiling:
    raise SystemExit(f"{phase} maxVUs {effective} exceeds operator ceiling {ceiling}")
print(effective)
PY
)"
  if [[ -n "$override" ]]; then
    export MAX_VUS="$override"
  else
    unset MAX_VUS
  fi
  export EFFECTIVE_MAX_VUS
}

case "$PHASE" in
  smoke)
    configure_phase_max_vus smoke ""
    ALLOW_K6_FAILURE=0 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" smoke "$run_dir"
    ;;
  ramp)
    export PREALLOCATED_VUS="${RAMP_PREALLOCATED_VUS:-20}"
    configure_phase_max_vus ramp "${RAMP_MAX_VUS:-}"
    # Ramp's own targetRate stages come from the profile and are already
    # bounded by profile.limits.maxRate inside load-tests/k6/aws/config.js
    # (enforceRateLimit). --max-rate/--max-vus here are the operator's
    # runtime ceiling on top of that.
    ALLOW_K6_FAILURE=0 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" ramp "$run_dir"
    ;;
  baseline)
    : "${CONFIRMED_RATE:?CONFIRMED_RATE is required for baseline (D-005 operator-confirmed arrival-rate)}"
    if [[ -n "$MAX_RATE" ]] && ! python3 -c "import sys; sys.exit(0 if float('$CONFIRMED_RATE') <= float('$MAX_RATE') else 1)"; then
      echo "--confirmed-rate $CONFIRMED_RATE exceeds --max-rate $MAX_RATE" >&2
      exit 2
    fi
    export RATE="$CONFIRMED_RATE"
    export PREALLOCATED_VUS="${BASELINE_PREALLOCATED_VUS:-20}"
    configure_phase_max_vus baseline "${BASELINE_MAX_VUS:-}"
    # Baseline reps are allowed to miss SLO thresholds (that is a legitimate,
    # expected outcome — see D-005 in aws-load-test-handoff/decisions/OPEN_DECISIONS.md,
    # "3회 중 하나라도 99% 미만이면 해당 arrival-rate 후보를 동결하지 않는다").
    # validate-aws-run.py, not this script's exit code, is the authority on
    # whether the candidate rate freezes.
    if [[ "$TARGET_PLATFORM" == "eks" ]]; then
      : "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required for EKS baseline observation}"
      : "${EKS_NODE_GROUP_NAME:?EKS_NODE_GROUP_NAME is required for EKS baseline observation}"
      : "${EKS_BASTION_ID:?EKS_BASTION_ID is required for EKS baseline observation}"
      : "${TARGET_GROUP_ARN:?TARGET_GROUP_ARN is required for EKS baseline observation}"
      # The observer starts before the k6 runner creates its own evidence
      # directory. Create the shared phase directory here so the redirection
      # and the observer's first snapshot cannot fail on a clean baseline.
      mkdir -p "$run_dir"
      observer_pid=""
      python3 "$REPOSITORY_ROOT/scripts/loadtest/aws/observe-aws-capacity-stress.py" \
        --run-dir "$run_dir" --metadata-file "$run_dir/metadata.json" \
        --platform eks --region "$REGION" --cluster-name "$EKS_CLUSTER_NAME" \
        --node-group-name "$EKS_NODE_GROUP_NAME" --eks-bastion-id "$EKS_BASTION_ID" \
        --target-group-arn "$TARGET_GROUP_ARN" --namespace "$BACKEND_NAMESPACE" \
        --deployment "$BACKEND_DEPLOYMENT" --eks-evidence-file "$EVIDENCE_ROOT/aws/eks-evidence.json" \
        --runner-stats-file "$run_dir/runner-stats.jsonl" --slo-window-file "$run_dir/slo-windows.jsonl" \
        --snapshot-file "$run_dir/snapshots.jsonl" --poll-seconds "${CAPACITY_OBSERVER_POLL_SECONDS:-10}" \
        > "$run_dir/observer.log" 2>&1 &
      observer_pid=$!
      set +e
      ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" baseline "$run_dir"
      baseline_status=$?
      if kill -0 "$observer_pid" 2>/dev/null; then kill "$observer_pid" 2>/dev/null || true; fi
      wait "$observer_pid" 2>/dev/null || true
      set -e
      exit "$baseline_status"
    fi
    ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" baseline "$run_dir"
    ;;
  spike)
    : "${CONFIRMED_RATE:?CONFIRMED_RATE is required for spike (peaks off the D-005 baseline rate)}"
    python3 - "$AWS_PROFILE_FILE" "$CONFIRMED_RATE" "$MAX_RATE" "${SPIKE_PEAK_MULTIPLIER:-}" <<'PY'
import json
import math
import sys
from pathlib import Path

profile_path, baseline_raw, operator_max_raw, multiplier_raw = sys.argv[1:]
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
scenario = profile.get("scenarios", {}).get("spike", {})
try:
    baseline = float(baseline_raw)
    operator_max = float(operator_max_raw)
    multiplier = float(multiplier_raw or scenario.get("peakRateMultiplier"))
    profile_max = float(profile.get("limits", {}).get("maxRate"))
except (TypeError, ValueError):
    raise SystemExit("spike baseline, multiplier, profile maxRate, and operator maxRate must be numbers")
if not all(math.isfinite(value) for value in (baseline, operator_max, multiplier, profile_max)):
    raise SystemExit("spike baseline, multiplier, profile maxRate, and operator maxRate must be finite")
if baseline <= 0:
    raise SystemExit("spike baseline rate must be positive")
if multiplier <= 1:
    raise SystemExit("spike peak multiplier must be greater than 1")
peak = baseline * multiplier
if not baseline < peak:
    raise SystemExit(f"spike peak rate {peak:g} must be greater than baseline rate {baseline:g}")
if peak > profile_max:
    raise SystemExit(
        f"spike peak rate {peak:g} exceeds profile limits.maxRate {profile_max:g}"
    )
if peak > operator_max:
    raise SystemExit(
        f"spike peak rate {peak:g} exceeds operator --max-rate {operator_max:g}"
    )
print(f"[b01] spike rate validated: baseline={baseline:g} peak={peak:g}")
PY
    export RATE="$CONFIRMED_RATE"
    export PREALLOCATED_VUS="${SPIKE_PREALLOCATED_VUS:-20}"
    configure_phase_max_vus spike "${SPIKE_MAX_VUS:-}"
    # Spike is diagnostic (b01SpikeThresholds is empty) — intentional peak
    # overload is expected, not a failure signal by itself.
    ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" spike "$run_dir"
    ;;
  soak)
    : "${CONFIRMED_RATE:?CONFIRMED_RATE is required for soak}"
    export RATE="$CONFIRMED_RATE"
    export PREALLOCATED_VUS="${SOAK_PREALLOCATED_VUS:-20}"
    configure_phase_max_vus soak "${SOAK_MAX_VUS:-}"
    ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" soak "$run_dir"
    ;;
  scale-step)
    : "${CONFIRMED_RATE:?CONFIRMED_RATE is required for scale-step}"
    export RATE="$CONFIRMED_RATE"
    export PREALLOCATED_VUS="${SCALE_STEP_PREALLOCATED_VUS:-20}"
    configure_phase_max_vus scale-step "${SCALE_STEP_MAX_VUS:-}"
    ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" scale-step "$run_dir"
    ;;
  capacity-stress)
    if [[ "$ADAPTIVE_BREAKPOINT" == "1" ]]; then
      : "${CAPACITY_TARGET_RATE:?CAPACITY_TARGET_RATE is required for adaptive capacity-stress}"
      target_values="$(python3 - "$CAPACITY_TARGET_RATE" "$MAX_VUS" "$AWS_PROFILE_FILE" <<'PY'
import json
import math
import sys
from pathlib import Path

target_raw, operator_raw, profile_path = sys.argv[1:]
try:
    target = float(target_raw)
    operator = int(operator_raw)
except (TypeError, ValueError):
    raise SystemExit("adaptive capacity target/maxVUs must be numeric")
if not math.isfinite(target) or target <= 0:
    raise SystemExit("adaptive capacity target rate must be positive")
preallocated = max(256, math.ceil(target))
max_vus = max(512, math.ceil(target * 2))
profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
profile_limit = int(profile["limits"]["maxVUs"])
if max_vus > profile_limit or max_vus > operator:
    raise SystemExit(f"adaptive stage maxVUs {max_vus} exceeds profile/operator limit")
print(f"{preallocated}|{max_vus}")
PY
)"
      IFS='|' read -r adaptive_preallocated adaptive_max_vus <<< "$target_values"
      export RATE="$CAPACITY_TARGET_RATE" CONFIRMED_RATE="$CAPACITY_TARGET_RATE"
      export PREALLOCATED_VUS="${CAPACITY_STRESS_PREALLOCATED_VUS:-$adaptive_preallocated}"
      export MAX_VUS="$adaptive_max_vus"
      export EFFECTIVE_MAX_VUS="$adaptive_max_vus"
      # Five minutes is long enough for HPA/Cluster Autoscaler observations
      # while keeping each adaptive stage bounded; the driver may extend one
      # active scale transition once, according to the v6 contract.
      export CAPACITY_STAGE_DURATION="${CAPACITY_STAGE_DURATION:-5m}"
      ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" capacity-stress "$run_dir"
    else
    : "${CONFIRMED_RATE:?CONFIRMED_RATE is required for capacity-stress (frozen normal rate)}"
    export RATE="$CONFIRMED_RATE"
    capacity_profile_preallocated_vus="$(python3 - "$AWS_PROFILE_FILE" <<'PY'
import json
import sys
from pathlib import Path

profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = profile.get("scenarios", {}).get("capacity-stress", {}).get("preAllocatedVUs")
if not isinstance(value, int) or value < 1:
    raise SystemExit("profile.scenarios.capacity-stress.preAllocatedVUs must be a positive integer")
print(value)
PY
)"
    export PREALLOCATED_VUS="${CAPACITY_STRESS_PREALLOCATED_VUS:-$capacity_profile_preallocated_vus}"
    capacity_profile_max_vus="$(python3 - "$AWS_PROFILE_FILE" <<'PY'
import json
import sys
from pathlib import Path

profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = profile.get("scenarios", {}).get("capacity-stress", {}).get("maxVUs")
if not isinstance(value, int) or value < 1:
    raise SystemExit("profile.scenarios.capacity-stress.maxVUs must be a positive integer")
print(value)
PY
)"
    configure_phase_max_vus capacity-stress "${CAPACITY_STRESS_MAX_VUS:-$capacity_profile_max_vus}"
    ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" capacity-stress "$run_dir"
    fi
    ;;
  pod-scale-out|node-scale-out-breakpoint|recovery)
    : "${CONFIRMED_RATE:?CONFIRMED_RATE is required for $PHASE}"
    export RATE="$CONFIRMED_RATE"
    export CAPACITY_STAGE="$PHASE"
    capacity_profile_preallocated_vus="$(python3 - "$AWS_PROFILE_FILE" <<'PY'
import json
import sys
from pathlib import Path

profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = profile.get("scenarios", {}).get("capacity-stress", {}).get("preAllocatedVUs")
if not isinstance(value, int) or value < 1:
    raise SystemExit("profile.scenarios.capacity-stress.preAllocatedVUs must be a positive integer")
print(value)
PY
)"
    export PREALLOCATED_VUS="${CAPACITY_STRESS_PREALLOCATED_VUS:-$capacity_profile_preallocated_vus}"
    capacity_profile_max_vus="$(python3 - "$AWS_PROFILE_FILE" <<'PY'
import json
import sys
from pathlib import Path

profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = profile.get("scenarios", {}).get("capacity-stress", {}).get("maxVUs")
if not isinstance(value, int) or value < 1:
    raise SystemExit("profile.scenarios.capacity-stress.maxVUs must be a positive integer")
print(value)
PY
)"
    configure_phase_max_vus capacity-stress "${CAPACITY_STRESS_MAX_VUS:-$capacity_profile_max_vus}"
    ALLOW_K6_FAILURE=1 "$REPOSITORY_ROOT/scripts/loadtest/aws/run-k6-aws-scenario.sh" capacity-stress "$run_dir"
    ;;
esac

echo "[b01] phase=$PHASE run_dir=$run_dir"
