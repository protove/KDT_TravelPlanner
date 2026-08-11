#!/usr/bin/env bash
# Operator guard to run before any `terraform destroy` of the dev-runtime
# environment (or any manual ephemeral-resource teardown) after a B-01 run.
#
# This is a PROCEDURAL gate, not a technical one: nothing in this repo can
# stop a human from running `terraform destroy` directly without ever
# calling this script first (see TEAM_MEMBER_B01_ACTION_REQUEST.md §6:
# "export gate를 통과하지 않은 direct terraform destroy를 orchestration이
# 차단하는 테스트 또는 운영 승인 절차" — a test OR an operational approval
# procedure; this repo has no Terraform-level hook into `destroy` to enforce
# it in code, so this script is the documented procedure half of that
# requirement). Treat it as a required step in the runbook, the same way
# the README already treats `apply`/`destroy` as separate-approval actions.
#
# It checks the local evidence bundle for the two artifacts orchestrate-aws-b01.sh
# only ever writes after a real, successful, gated export:
#   - freeze-metadata.json   (D-006 approval was recorded)
#   - export-complete.json   (upload-aws-evidence.py's final export ran to completion)
#
# Neither file re-verifies that the S3 objects actually exist (that would
# require a real `aws s3api head-object` call, out of scope for a local
# pre-destroy sanity check) — it only proves this Runner's orchestration
# reached the export step and it returned success.
set -euo pipefail

EVIDENCE_ROOT="${1:?usage: check-destroy-gate.sh <evidence-root>}"

if [[ ! -d "$EVIDENCE_ROOT" ]]; then
  echo "[destroy-gate] evidence root does not exist: $EVIDENCE_ROOT" >&2
  exit 2
fi

missing=()
[[ -f "$EVIDENCE_ROOT/freeze-metadata.json" ]] || missing+=("freeze-metadata.json (D-006 not approved)")
[[ -f "$EVIDENCE_ROOT/export-complete.json" ]] || missing+=("export-complete.json (final export did not complete)")

if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "[destroy-gate] BLOCKED: $EVIDENCE_ROOT is not safe to destroy against yet." >&2
  for reason in "${missing[@]}"; do
    echo "  - missing: $reason" >&2
  done
  exit 1
fi

echo "[destroy-gate] OK: $EVIDENCE_ROOT has freeze-metadata.json and export-complete.json."
echo "[destroy-gate] This does not verify the S3 upload independently — if in doubt, check the bucket directly before destroying."
