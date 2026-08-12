#!/usr/bin/env bash
# Validate (and, only when explicitly requested, build) the AWS recovery fault
# fixture. This helper never pushes an image unless --push is supplied.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
CONTEXT="$REPOSITORY_ROOT/load-tests/fault-images/aws-recovery"

IMAGE_REF=""
BASE_IMAGE=""
DO_BUILD=0
DO_PUSH=0

usage() {
  cat <<'EOF'
usage: build-recovery-fault-image.sh --image-ref REPOSITORY:TAG \
  --base-image python:3.12-alpine@sha256:<64-hex> [--dry-run | --build] [--push]

--dry-run is the default and validates only. --push requires --build and is a
separate live approval action.
EOF
}

while (($#)); do
  case "$1" in
    --image-ref) IMAGE_REF="${2:?missing value for --image-ref}"; shift 2 ;;
    --base-image) BASE_IMAGE="${2:?missing value for --base-image}"; shift 2 ;;
    --build) DO_BUILD=1; shift ;;
    --dry-run) DO_BUILD=0; shift ;;
    --push) DO_PUSH=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$IMAGE_REF" || -z "$BASE_IMAGE" ]]; then
  usage >&2
  exit 2
fi
if [[ "$IMAGE_REF" != *:* || "$IMAGE_REF" == *@* ]]; then
  echo "--image-ref must be a mutable build tag without a digest" >&2
  exit 2
fi
if [[ ! "$BASE_IMAGE" =~ ^python:3\.12-alpine@sha256:[0-9a-f]{64}$ ]]; then
  echo "--base-image must be python:3.12-alpine@sha256:<64 lowercase hex>" >&2
  exit 2
fi
if (( DO_PUSH && !DO_BUILD )); then
  echo "--push requires --build; no push was attempted" >&2
  exit 2
fi
if [[ ! -f "$CONTEXT/Dockerfile" || ! -f "$CONTEXT/server.py" || ! -f "$CONTEXT/artifact-contract.json" ]]; then
  echo "fault fixture context is incomplete: $CONTEXT" >&2
  exit 2
fi

python3 - "$IMAGE_REF" "$BASE_IMAGE" "$CONTEXT/artifact-contract.json" <<'PY'
import json
import re
import sys
from pathlib import Path

image_ref, base_image, contract_path = sys.argv[1:]
contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
if "@" in image_ref:
    raise SystemExit("build image reference must not contain a digest")
if not re.fullmatch(r"python:3\.12-alpine@sha256:[0-9a-f]{64}", base_image):
    raise SystemExit("base image is not digest pinned")
if contract["image"]["requiresDigest"] is not True:
    raise SystemExit("artifact contract must require a digest")
print(f"artifact_contract=verified image_ref={image_ref} base_image={base_image}")
PY

if (( ! DO_BUILD )); then
  echo "dry_run=passed"
  exit 0
fi

docker build \
  --pull=false \
  --build-arg "PYTHON_IMAGE=$BASE_IMAGE" \
  --tag "$IMAGE_REF" \
  "$CONTEXT"

echo "image_build=passed local_tag=$IMAGE_REF"
if (( DO_PUSH )); then
  docker push "$IMAGE_REF"
  echo "image_push=completed local_tag=$IMAGE_REF"
  echo "next_step=record_registry_digest_as_RECOVERY_FAULT_IMAGE_DIGEST"
fi
