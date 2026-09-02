#!/usr/bin/env bash
# Thin SCRUM-80 lifecycle guard: context/deadline validation and one cleanup
# lock only. AWS/Terraform provisioning and workload stages remain owned by
# their reviewed callers.
set -euo pipefail

CONTEXT_FILE=""
CLEANUP_LOCK=""
DRY_RUN=0
RELEASE_LOCK=0
COMMAND=()
COMMAND_COUNT=0

usage() {
  cat <<'USAGE'
usage: run-scrum80-lifecycle.sh --context PATH --cleanup-lock PATH [options] -- COMMAND [ARGS...]
       run-scrum80-lifecycle.sh --context PATH --cleanup-lock PATH --release-lock

Required:
  --context PATH       Secret-free JSON with runId and lifecycle policy. Legacy contexts also carry deadlineUtc/reserveMinutes.
  --cleanup-lock PATH  Exact absolute lock directory ending in scrum80-lifecycle.lock

Options:
  --dry-run             Validate without creating the lock or running COMMAND
  --release-lock        Release the exact lock after cleanup verification
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --context)
      [[ "$#" -ge 2 ]] || { echo "--context needs a path" >&2; exit 2; }
      CONTEXT_FILE="$2"; shift 2 ;;
    --cleanup-lock)
      [[ "$#" -ge 2 ]] || { echo "--cleanup-lock needs a path" >&2; exit 2; }
      CLEANUP_LOCK="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --release-lock) RELEASE_LOCK=1; shift ;;
    --)
      shift
      COMMAND=("$@")
      COMMAND_COUNT="$#"
      break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$CONTEXT_FILE" || -z "$CLEANUP_LOCK" ]]; then
  echo "--context and --cleanup-lock are required" >&2
  exit 2
fi
if [[ "$CONTEXT_FILE" != /* || ! -f "$CONTEXT_FILE" ]]; then
  echo "--context must be an existing absolute file" >&2
  exit 2
fi
if [[ "$CLEANUP_LOCK" != /* || "$CLEANUP_LOCK" == "/" || "$(basename "$CLEANUP_LOCK")" != "scrum80-lifecycle.lock" ]]; then
  echo "--cleanup-lock must be an absolute path ending in scrum80-lifecycle.lock" >&2
  exit 2
fi
if [[ "$RELEASE_LOCK" == "1" && "$DRY_RUN" == "1" ]]; then
  echo "--release-lock and --dry-run cannot be combined" >&2
  exit 2
fi
if [[ "$RELEASE_LOCK" != "1" && "$DRY_RUN" != "1" && "$COMMAND_COUNT" -eq 0 ]]; then
  echo "a command after -- is required unless --release-lock is used" >&2
  exit 2
fi

context_line="$(python3 - "$CONTEXT_FILE" <<'PY'
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"invalid lifecycle context: {error}")
if not isinstance(payload, dict):
    raise SystemExit("lifecycle context must be a JSON object")
run_id = payload.get("runId")
if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
    raise SystemExit("context.runId is invalid")
policy = payload.get("policy", "legacy-deadline-reserve")
if policy == "until-validated-terminal-and-closure":
    deadline_raw = None
    reserve = None
    remaining = None
elif policy == "legacy-deadline-reserve":
    deadline_raw = payload.get("deadlineUtc")
    if not isinstance(deadline_raw, str) or not deadline_raw.endswith("Z"):
        raise SystemExit("context.deadlineUtc must be an ISO-8601 UTC timestamp ending in Z")
    try:
        deadline = datetime.fromisoformat(deadline_raw[:-1] + "+00:00")
    except ValueError as error:
        raise SystemExit(f"context.deadlineUtc is invalid: {error}")
    if deadline.tzinfo != timezone.utc:
        raise SystemExit("context.deadlineUtc must use UTC")
    reserve = payload.get("reserveMinutes")
    if not isinstance(reserve, int) or reserve < 0:
        raise SystemExit("context.reserveMinutes must be a non-negative integer")
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
else:
    raise SystemExit("context.policy is unsupported")
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print("\t".join((policy, run_id, deadline_raw or "-", "-" if reserve is None else str(reserve), "-" if remaining is None else f"{remaining:.3f}", digest)))
PY
)"
IFS=$'\t' read -r LIFECYCLE_POLICY RUN_ID DEADLINE_UTC RESERVE_MINUTES REMAINING_SECONDS CONTEXT_SHA256 <<< "$context_line"
[[ "$DEADLINE_UTC" == "-" ]] && DEADLINE_UTC=""
[[ "$RESERVE_MINUTES" == "-" ]] && RESERVE_MINUTES=""
[[ "$REMAINING_SECONDS" == "-" ]] && REMAINING_SECONDS=""

if [[ "$RELEASE_LOCK" != "1" && "$LIFECYCLE_POLICY" == "legacy-deadline-reserve" ]]; then
  python3 - "$REMAINING_SECONDS" "$RESERVE_MINUTES" <<'PY'
import sys
if float(sys.argv[1]) <= int(sys.argv[2]) * 60:
    raise SystemExit("lifecycle deadline/reserve is already exhausted")
PY
fi

if [[ "$RELEASE_LOCK" == "1" ]]; then
  if [[ ! -d "$CLEANUP_LOCK" || ! -f "$CLEANUP_LOCK/metadata.json" ]]; then
    echo "cleanup lock is not held: $CLEANUP_LOCK" >&2
    exit 1
  fi
  python3 - "$CLEANUP_LOCK/metadata.json" "$RUN_ID" "$CONTEXT_SHA256" <<'PY'
import json
import sys
from pathlib import Path

metadata, expected_run, expected_context = sys.argv[1:]
payload = json.loads(Path(metadata).read_text(encoding="utf-8"))
if payload.get("runId") != expected_run or payload.get("contextSha256") != expected_context:
    raise SystemExit("cleanup lock does not match the supplied context")
PY
  rm -- "$CLEANUP_LOCK/metadata.json"
  rmdir -- "$CLEANUP_LOCK"
  printf '%s\n' "[scrum80-lifecycle] released cleanup lock for $RUN_ID"
  exit 0
fi

if [[ "$DRY_RUN" == "1" ]]; then
  python3 - "$LIFECYCLE_POLICY" "$RUN_ID" "$DEADLINE_UTC" "$RESERVE_MINUTES" "$REMAINING_SECONDS" "$CONTEXT_SHA256" "$COMMAND_COUNT" <<'PY'
import json
import sys
policy, run_id, deadline, reserve, remaining, context_sha, command_count = sys.argv[1:]
print(json.dumps({
    "policy": policy,
    "runId": run_id,
    "deadlineUtc": deadline or None,
    "reserveMinutes": int(reserve) if reserve else None,
    "remainingSeconds": float(remaining) if remaining else None,
    "contextSha256": context_sha,
    "lockPathValidated": True,
    "commandArgumentCount": int(command_count),
    "lockCreated": False,
}, sort_keys=True))
PY
  exit 0
fi

mkdir -p "$(dirname "$CLEANUP_LOCK")"
if ! mkdir "$CLEANUP_LOCK" 2>/dev/null; then
  echo "cleanup lock is already held: $CLEANUP_LOCK" >&2
  exit 1
fi
python3 - "$CLEANUP_LOCK/metadata.json" "$LIFECYCLE_POLICY" "$RUN_ID" "$DEADLINE_UTC" "$RESERVE_MINUTES" "$CONTEXT_SHA256" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path, policy, run_id, deadline, reserve, context_sha = sys.argv[1:]
Path(path).write_text(json.dumps({
    "schemaVersion": "scrum80-lifecycle-lock/v1",
    "policy": policy,
    "runId": run_id,
    "deadlineUtc": deadline or None,
    "reserveMinutes": int(reserve) if reserve else None,
    "contextSha256": context_sha,
    "pid": os.getppid(),
    "status": "running",
    "startedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2) + "\n", encoding="utf-8")
PY

set +e
"${COMMAND[@]}"
command_status="$?"
set -e
python3 - "$CLEANUP_LOCK/metadata.json" "$command_status" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["status"] = "succeeded" if int(sys.argv[2]) == 0 else "command-failed"
payload["commandExitCode"] = int(sys.argv[2])
payload["finishedAtUtc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
exit "$command_status"
