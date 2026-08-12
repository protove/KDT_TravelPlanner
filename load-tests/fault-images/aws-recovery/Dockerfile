# syntax=docker/dockerfile:1.7
#
# The build helper requires PYTHON_IMAGE to be a digest-pinned Python Alpine
# image. A mutable default is intentionally not provided here: the operator
# must supply the approved base image digest at build time.
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}

ARG APP_UID=10001
ARG APP_GID=10001
ARG CONTRACT_VERSION=aws-recovery-fault-image-v1
ARG FAULT_MODE=normal
ARG FAULT_PATH=/api/v1/travels
ARG FAULT_ERROR_CODE=INTERNAL_SERVER_ERROR
ARG FAULT_ERROR_MESSAGE=서버 내부 오류가 발생했습니다.
ARG FAULT_HTTP_STATUS=500
ARG FAULT_CONFIG_B64
ARG BEHAVIOR_SHA256
WORKDIR /app

RUN addgroup -S -g "${APP_GID}" faultfixture \
    && adduser -S -D -H -u "${APP_UID}" -G faultfixture faultfixture

COPY server.py artifact-contract.json ./
RUN FAULT_CONFIG_B64="${FAULT_CONFIG_B64}" \
    BEHAVIOR_SHA256="${BEHAVIOR_SHA256}" \
    python - <<'PY'
import base64
import hashlib
import json
import os
from pathlib import Path

encoded = os.environ.get("FAULT_CONFIG_B64", "")
expected_sha = os.environ.get("BEHAVIOR_SHA256", "")
if not encoded or not expected_sha:
    raise SystemExit("FAULT_CONFIG_B64 and BEHAVIOR_SHA256 are required")
try:
    config = json.loads(base64.b64decode(encoded).decode("utf-8"))
except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"invalid immutable fault configuration: {error}") from error
canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
actual_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
if actual_sha != expected_sha:
    raise SystemExit("immutable fault configuration digest mismatch")
Path("/app/fault-config.json").write_text(
    json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

LABEL org.kdt.travelplanner.recovery.contract-version="${CONTRACT_VERSION}"
LABEL org.kdt.travelplanner.recovery.behavior-sha256="${BEHAVIOR_SHA256}"

RUN chown -R faultfixture:faultfixture /app

USER faultfixture
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    MANAGEMENT_PORT=9091 \
    IMMUTABLE_BEHAVIOR_SHA256=${BEHAVIOR_SHA256} \
    IMMUTABLE_CONTRACT_VERSION=${CONTRACT_VERSION}

EXPOSE 8080 9091
ENTRYPOINT ["python", "/app/server.py"]
