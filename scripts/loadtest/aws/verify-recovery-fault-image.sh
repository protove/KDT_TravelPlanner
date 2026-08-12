#!/usr/bin/env bash
# Validate the exact image references that may be handed to an AWS recovery
# deployment. This performs no registry, Docker, Terraform, or AWS action.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
CONTRACT="$REPOSITORY_ROOT/load-tests/fault-images/aws-recovery/artifact-contract.json"
DOCKER_BIN="${DOCKER_BIN:-docker}"

IMAGE_REF=""
BASE_IMAGE=""
METADATA_FILE=""
MODE=""
FAULT_PATH="/api/v1/travels"
FAULT_ERROR_CODE="INTERNAL_SERVER_ERROR"
FAULT_ERROR_MESSAGE="서버 내부 오류가 발생했습니다."
FAULT_HTTP_STATUS="500"
while (($#)); do
  case "$1" in
    --image-ref) IMAGE_REF="${2:?missing value for --image-ref}"; shift 2 ;;
    --base-image) BASE_IMAGE="${2:?missing value for --base-image}"; shift 2 ;;
    --metadata-file|--artifact-metadata|--metadata) METADATA_FILE="${2:?missing value for --metadata-file}"; shift 2 ;;
    --mode) MODE="${2:?missing value for --mode}"; shift 2 ;;
    --fault-path) FAULT_PATH="${2:?missing value for --fault-path}"; shift 2 ;;
    --fault-error-code) FAULT_ERROR_CODE="${2:?missing value for --fault-error-code}"; shift 2 ;;
    --fault-error-message) FAULT_ERROR_MESSAGE="${2:?missing value for --fault-error-message}"; shift 2 ;;
    --fault-http-status) FAULT_HTTP_STATUS="${2:?missing value for --fault-http-status}"; shift 2 ;;
    -h|--help)
      echo "usage: verify-recovery-fault-image.sh --image-ref REPOSITORY:TAG@sha256:<64-hex> --base-image python:3.12-alpine@sha256:<64-hex> --mode MODE --metadata-file artifact-metadata.json"
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
if [[ -z "$MODE" ]]; then
  echo "--mode is required to bind the selected fault behavior" >&2
  exit 2
fi
if [[ -z "$METADATA_FILE" || ! -f "$METADATA_FILE" ]]; then
  echo "--metadata-file is required and must point to an artifact metadata file" >&2
  exit 2
fi

INSPECT_JSON="$(mktemp "${TMPDIR:-/tmp}/recovery-fault-image-inspect.XXXXXX")"
INSPECT_ERR="$(mktemp "${TMPDIR:-/tmp}/recovery-fault-image-inspect-error.XXXXXX")"
trap 'rm -f "$INSPECT_JSON" "$INSPECT_ERR"' EXIT
if ! "$DOCKER_BIN" image inspect "$IMAGE_REF" >"$INSPECT_JSON" 2>"$INSPECT_ERR"; then
  echo "docker image inspect failed for the exact digest-pinned image" >&2
  exit 1
fi

python3 - "$CONTRACT" "$METADATA_FILE" "$IMAGE_REF" "$BASE_IMAGE" \
  "$MODE" "$FAULT_PATH" "$FAULT_ERROR_CODE" "$FAULT_ERROR_MESSAGE" "$FAULT_HTTP_STATUS" \
  "$INSPECT_JSON" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

(
    contract_path,
    metadata_path,
    image_ref,
    base_image,
    mode,
    fault_path,
    fault_error_code,
    fault_error_message,
    fault_http_status,
    inspect_path,
) = sys.argv[1:]
try:
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"unable to read artifact contract: {error}") from error
if contract.get("contractVersion") != "aws-recovery-fault-image-v1":
    raise SystemExit("unexpected fault image contract version")
image_spec = contract.get("image", {})
if image_spec.get("requiresDigest") is not True:
    raise SystemExit("fault image contract does not require a deployment digest")
if image_spec.get("baseImageRequiresDigest") is not True:
    raise SystemExit("fault image contract does not require a base image digest")
if not re.fullmatch(image_spec.get("digestPattern", ""), image_ref):
    raise SystemExit("image reference is not digest pinned")
if not re.fullmatch(image_spec.get("baseImagePattern", ""), base_image):
    raise SystemExit("base image is not digest pinned")

try:
    inspected = json.loads(Path(inspect_path).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"unable to read docker image inspection: {error}") from error
if not isinstance(inspected, list) or len(inspected) != 1 or not isinstance(inspected[0], dict):
    raise SystemExit("docker image inspection must contain exactly one image")
image = inspected[0]
repo_digests = image.get("RepoDigests")
if not isinstance(repo_digests, list):
    raise SystemExit("docker image inspection does not prove the exact deployment digest")
image_tag, image_digest = image_ref.split("@", 1)
repository = image_tag.rsplit(":", 1)[0]
expected_repo_digest = f"{repository}@{image_digest}"
if expected_repo_digest not in repo_digests:
    raise SystemExit("docker image inspection does not prove the exact deployment digest")
config = image.get("Config")
if not isinstance(config, dict):
    raise SystemExit("docker image inspection is missing image config")
labels = config.get("Labels")
if not isinstance(labels, dict):
    raise SystemExit("docker image inspection is missing immutable recovery labels")

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

behavior_config = {
    "contractVersion": contract.get("contractVersion"),
    "mode": mode,
    "faultPath": fault_path,
    "faultErrorCode": fault_error_code,
    "faultErrorMessage": fault_error_message,
    "faultHttpStatus": status,
}
canonical = json.dumps(behavior_config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
behavior_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
label_prefix = "org.kdt.travelplanner.recovery."
if labels.get(label_prefix + "contract-version") != contract.get("contractVersion"):
    raise SystemExit("image label contract version does not match the artifact contract")
if labels.get(label_prefix + "behavior-sha256") != behavior_sha:
    raise SystemExit("image immutable behavior digest does not match selected parameters")
environment = config.get("Env")
if not isinstance(environment, list):
    raise SystemExit("docker image inspection is missing image environment")
for variable in (
    "FAULT_MODE",
    "FAULT_PATH",
    "FAULT_ERROR_CODE",
    "FAULT_ERROR_MESSAGE",
    "FAULT_HTTP_STATUS",
):
    if any(isinstance(item, str) and item.startswith(variable + "=") for item in environment):
        raise SystemExit(f"image contains runtime-overridable {variable}; immutable config is required")
if f"IMMUTABLE_BEHAVIOR_SHA256={behavior_sha}" not in environment:
    raise SystemExit("image immutable behavior environment binding is missing")
if f"IMMUTABLE_CONTRACT_VERSION={contract.get('contractVersion')}" not in environment:
    raise SystemExit("image immutable contract environment binding is missing")

try:
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
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
    "imageRef": image_ref,
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
print("fault_image_contract=verified")
print(f"artifact_metadata=derived_from_image mode={mode} image_ref={image_ref}")
print(f"immutable_behavior_sha256=verified value={behavior_sha}")
PY

echo "deployment_image_ref=verified"
echo "base_image_ref=verified"
