#!/usr/bin/env bash
# Validate (and, only when explicitly requested, build) the AWS recovery fault
# fixture. This helper never pushes an image unless --push is supplied.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
CONTEXT="$REPOSITORY_ROOT/load-tests/fault-images/aws-recovery"

IMAGE_REF=""
BASE_IMAGE=""
IMAGE_DIGEST=""
METADATA_FILE=""
MODE="normal"
FAULT_PATH="/api/v1/travels"
FAULT_ERROR_CODE="INTERNAL_SERVER_ERROR"
FAULT_ERROR_MESSAGE="서버 내부 오류가 발생했습니다."
FAULT_HTTP_STATUS="500"
DO_BUILD=0
DO_PUSH=0

usage() {
  cat <<'EOF'
usage: build-recovery-fault-image.sh --image-ref REPOSITORY:TAG \
  --base-image python:3.12-alpine@sha256:<64-hex> [--mode MODE] \
  [--dry-run | --build] [--push]

--dry-run is the default and validates only. --push requires --build and is a
separate live approval action. When a registry digest is known, --image-digest
and --metadata-file pre-validate the sidecar; verify-recovery-fault-image.sh
must still inspect the exact local image digest and immutable config.
EOF
}

while (($#)); do
  case "$1" in
    --image-ref) IMAGE_REF="${2:?missing value for --image-ref}"; shift 2 ;;
    --base-image) BASE_IMAGE="${2:?missing value for --base-image}"; shift 2 ;;
    --image-digest) IMAGE_DIGEST="${2:?missing value for --image-digest}"; shift 2 ;;
    --metadata-file|--artifact-metadata|--metadata) METADATA_FILE="${2:?missing value for --metadata-file}"; shift 2 ;;
    --mode) MODE="${2:?missing value for --mode}"; shift 2 ;;
    --fault-path) FAULT_PATH="${2:?missing value for --fault-path}"; shift 2 ;;
    --fault-error-code) FAULT_ERROR_CODE="${2:?missing value for --fault-error-code}"; shift 2 ;;
    --fault-error-message) FAULT_ERROR_MESSAGE="${2:?missing value for --fault-error-message}"; shift 2 ;;
    --fault-http-status) FAULT_HTTP_STATUS="${2:?missing value for --fault-http-status}"; shift 2 ;;
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

python3 - "$IMAGE_REF" "$BASE_IMAGE" "$IMAGE_DIGEST" "$METADATA_FILE" \
  "$MODE" "$FAULT_PATH" "$FAULT_ERROR_CODE" "$FAULT_ERROR_MESSAGE" "$FAULT_HTTP_STATUS" \
  "$CONTEXT/artifact-contract.json" <<'PY'
import json
import re
import sys
from pathlib import Path

(
    image_ref,
    base_image,
    image_digest,
    metadata_file,
    mode,
    fault_path,
    fault_error_code,
    fault_error_message,
    fault_http_status,
    contract_path,
) = sys.argv[1:]

try:
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"unable to read artifact contract: {error}") from error

if "@" in image_ref:
    raise SystemExit("build image reference must not contain a digest")
image_spec = contract.get("image", {})
if image_spec.get("requiresDigest") is not True:
    raise SystemExit("artifact contract must require a deployment digest")
if image_spec.get("baseImageRequiresDigest") is not True:
    raise SystemExit("artifact contract must require a base image digest")
if not re.fullmatch(image_spec.get("baseImagePattern", ""), base_image):
    raise SystemExit("base image is not digest pinned")

metadata_spec = contract.get("metadata")
if not isinstance(metadata_spec, dict):
    raise SystemExit("artifact contract is missing metadata specification")
required_fields = metadata_spec.get("requiredFields")
if not isinstance(required_fields, list) or not required_fields:
    raise SystemExit("artifact contract metadata requiredFields is invalid")
canonical_fields = {
    "contractVersion",
    "imageRef",
    "baseImage",
    "mode",
    "faultPath",
    "faultErrorCode",
    "faultErrorMessage",
    "faultHttpStatus",
}
if len(required_fields) != len(canonical_fields) or set(required_fields) != canonical_fields:
    raise SystemExit("artifact contract metadata fields are not the canonical set")
modes = contract.get("modes")
if not isinstance(modes, dict) or mode not in modes:
    raise SystemExit(f"unknown fault mode: {mode}")
for declared_mode, values in modes.items():
    if not isinstance(values, dict) or not isinstance(values.get("readinessStatus"), int):
        raise SystemExit(f"missing readiness status for mode: {declared_mode}")

fault_parameters = metadata_spec.get("faultParameters")
if not isinstance(fault_parameters, dict):
    raise SystemExit("artifact contract metadata faultParameters is invalid")
path_spec = fault_parameters.get("faultPath", {})
code_spec = fault_parameters.get("faultErrorCode", {})
message_spec = fault_parameters.get("faultErrorMessage", {})
status_spec = fault_parameters.get("faultHttpStatus", {})
if not isinstance(path_spec.get("pattern"), str) or not re.fullmatch(path_spec["pattern"], fault_path):
    raise SystemExit("FAULT_PATH is not a safe /api/v1/... path")
if not isinstance(code_spec.get("pattern"), str) or not re.fullmatch(code_spec["pattern"], fault_error_code):
    raise SystemExit("FAULT_ERROR_CODE must be an uppercase error code")
if not isinstance(fault_error_message, str) or len(fault_error_message) > int(message_spec.get("maxLength", 256)):
    raise SystemExit("FAULT_ERROR_MESSAGE must be at most 256 characters")
try:
    status = int(fault_http_status)
except ValueError as error:
    raise SystemExit("FAULT_HTTP_STATUS must be an integer") from error
if not int(status_spec.get("minimum", 500)) <= status <= int(status_spec.get("maximum", 599)):
    raise SystemExit("FAULT_HTTP_STATUS must be between 500 and 599")

if image_digest:
    if not re.fullmatch(image_spec.get("digestPattern", ""), image_digest):
        raise SystemExit("--image-digest must be a digest-pinned registry reference")
elif metadata_file:
    raise SystemExit("--metadata-file requires --image-digest")

if metadata_file:
    if not image_digest:
        raise SystemExit("--metadata-file requires --image-digest")
    try:
        metadata = json.loads(Path(metadata_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"unable to read artifact metadata: {error}") from error
    if not isinstance(metadata, dict):
        raise SystemExit("artifact metadata must be a JSON object")
    expected_keys = set(required_fields)
    if set(metadata) != expected_keys:
        missing = sorted(expected_keys - set(metadata))
        unexpected = sorted(set(metadata) - expected_keys)
        raise SystemExit(f"artifact metadata fields mismatch missing={missing} unexpected={unexpected}")
    expected = {
        "contractVersion": contract.get("contractVersion"),
        "imageRef": image_digest,
        "baseImage": base_image,
        "mode": mode,
        "faultPath": fault_path,
        "faultErrorCode": fault_error_code,
        "faultErrorMessage": fault_error_message,
        "faultHttpStatus": status,
    }
    for field, value in expected.items():
        if metadata.get(field) != value:
            raise SystemExit(f"artifact metadata mismatch for {field}")

print(f"artifact_contract=verified image_ref={image_ref} base_image={base_image}")
print(f"fault_mode=verified mode={mode}")
if metadata_file:
    print(f"artifact_metadata=verified image_digest={image_digest}")
PY

BUILD_BINDING="$({
  python3 - "$MODE" "$FAULT_PATH" "$FAULT_ERROR_CODE" "$FAULT_ERROR_MESSAGE" \
    "$FAULT_HTTP_STATUS" "$CONTEXT/artifact-contract.json" <<'PY'
import base64
import hashlib
import json
import sys
from pathlib import Path

mode, fault_path, fault_error_code, fault_error_message, fault_http_status, contract_path = sys.argv[1:]
contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
config = {
    "contractVersion": contract["contractVersion"],
    "mode": mode,
    "faultPath": fault_path,
    "faultErrorCode": fault_error_code,
    "faultErrorMessage": fault_error_message,
    "faultHttpStatus": int(fault_http_status),
}
canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
encoded = base64.b64encode(canonical.encode("utf-8")).decode("ascii")
digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
print(f"{encoded}:{digest}")
PY
})"
FAULT_CONFIG_B64="${BUILD_BINDING%%:*}"
BEHAVIOR_SHA256="${BUILD_BINDING##*:}"
echo "behavior_binding=derived sha256=$BEHAVIOR_SHA256"

if (( ! DO_BUILD )); then
  echo "dry_run=passed"
  exit 0
fi

docker build \
  --pull=false \
  --build-arg "PYTHON_IMAGE=$BASE_IMAGE" \
  --build-arg "CONTRACT_VERSION=aws-recovery-fault-image-v1" \
  --build-arg "FAULT_MODE=$MODE" \
  --build-arg "FAULT_PATH=$FAULT_PATH" \
  --build-arg "FAULT_ERROR_CODE=$FAULT_ERROR_CODE" \
  --build-arg "FAULT_ERROR_MESSAGE=$FAULT_ERROR_MESSAGE" \
  --build-arg "FAULT_HTTP_STATUS=$FAULT_HTTP_STATUS" \
  --build-arg "FAULT_CONFIG_B64=$FAULT_CONFIG_B64" \
  --build-arg "BEHAVIOR_SHA256=$BEHAVIOR_SHA256" \
  --tag "$IMAGE_REF" \
  "$CONTEXT"

echo "image_build=passed local_tag=$IMAGE_REF behavior_sha256=$BEHAVIOR_SHA256"
if (( DO_PUSH )); then
  docker push "$IMAGE_REF"
  echo "image_push=completed local_tag=$IMAGE_REF"
  echo "next_step=record_registry_digest_as_RECOVERY_FAULT_IMAGE_DIGEST"
fi
