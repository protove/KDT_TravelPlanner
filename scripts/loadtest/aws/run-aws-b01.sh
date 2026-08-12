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

PHASE="${1:?usage: run-aws-b01.sh <smoke|ramp|baseline|spike> [rep]}"
REP="${2:-}"

: "${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
: "${EVIDENCE_ROOT:?EVIDENCE_ROOT is required}"
: "${BASE_URL:?BASE_URL is required}"
: "${K6_IMAGE_DIGEST:?K6_IMAGE_DIGEST is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${AWS_PROFILE_FILE:?AWS_PROFILE_FILE is required}"
: "${REGION:?REGION is required}"
: "${ENVIRONMENT:?ENVIRONMENT is required}"
MAX_RATE="${MAX_RATE:?MAX_RATE is required}"
OPERATOR_MAX_VUS="${MAX_VUS:?MAX_VUS is required}"

case "$PHASE" in
  smoke|ramp|baseline|spike) ;;
  *) echo "usage: run-aws-b01.sh <smoke|ramp|baseline|spike> [rep]" >&2; exit 2 ;;
esac
if [[ "$PHASE" == "baseline" && -z "$REP" ]]; then
  echo "baseline requires a rep number (1-3): run-aws-b01.sh baseline <rep>" >&2
  exit 2
fi

suffix="$PHASE"
[[ -n "$REP" ]] && suffix="$PHASE-$REP"
run_dir="$EVIDENCE_ROOT/k6/$suffix"
phase_run_id="$RUN_ID-$suffix"

export REPOSITORY_ROOT BASE_URL K6_IMAGE_DIGEST AWS_PROFILE_FILE REGION ENVIRONMENT
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
scenario = profile.get("scenarios", {}).get(phase, {})
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
    if ! python3 -c "import sys; sys.exit(0 if float('$CONFIRMED_RATE') <= float('$MAX_RATE') else 1)"; then
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
esac

echo "[b01] phase=$PHASE run_dir=$run_dir"
