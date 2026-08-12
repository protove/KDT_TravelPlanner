#!/usr/bin/env bash
# Validate the exact image references that may be handed to an AWS recovery
# deployment. This performs no registry, Docker, Terraform, or AWS action.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
CONTRACT="$REPOSITORY_ROOT/load-tests/fault-images/aws-recovery/artifact-contract.json"

IMAGE_REF=""
BASE_IMAGE=""
while (($#)); do
  case "$1" in
    --image-ref) IMAGE_REF="${2:?missing value for --image-ref}"; shift 2 ;;
    --base-image) BASE_IMAGE="${2:?missing value for --base-image}"; shift 2 ;;
    -h|--help)
      echo "usage: verify-recovery-fault-image.sh --image-ref REPOSITORY:TAG@sha256:<64-hex> --base-image python:3.12-alpine@sha256:<64-hex>"
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! "$IMAGE_REF" =~ ^[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "--image-ref must be a digest-pinned registry reference" >&2
  exit 2
fi
if [[ ! "$BASE_IMAGE" =~ ^python:3\.12-alpine@sha256:[0-9a-f]{64}$ ]]; then
  echo "--base-image must be python:3.12-alpine@sha256:<64 lowercase hex>" >&2
  exit 2
fi

python3 - "$CONTRACT" <<'PY'
import json
import sys
from pathlib import Path

contract = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if contract.get("contractVersion") != "aws-recovery-fault-image-v1":
    raise SystemExit("unexpected fault image contract version")
if contract.get("image", {}).get("requiresDigest") is not True:
    raise SystemExit("fault image contract does not require a deployment digest")
if contract.get("image", {}).get("baseImageRequiresDigest") is not True:
    raise SystemExit("fault image contract does not require a base image digest")
for mode, values in contract.get("modes", {}).items():
    if mode not in {"normal", "probe_failure", "business_error"}:
        raise SystemExit(f"unknown fault mode: {mode}")
    if not isinstance(values.get("readinessStatus"), int):
        raise SystemExit(f"missing readiness status for mode: {mode}")
print("fault_image_contract=verified")
PY

echo "deployment_image_ref=verified"
echo "base_image_ref=verified"
