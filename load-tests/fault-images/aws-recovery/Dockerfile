# syntax=docker/dockerfile:1.7
#
# The build helper requires PYTHON_IMAGE to be a digest-pinned Python Alpine
# image. A mutable default is intentionally not provided here: the operator
# must supply the approved base image digest at build time.
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}

ARG APP_UID=10001
ARG APP_GID=10001
WORKDIR /app

RUN addgroup -S -g "${APP_GID}" faultfixture \
    && adduser -S -D -H -u "${APP_UID}" -G faultfixture faultfixture

COPY server.py artifact-contract.json ./
RUN chown -R faultfixture:faultfixture /app

USER faultfixture
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    MANAGEMENT_PORT=9091 \
    FAULT_MODE=normal \
    FAULT_PATH=/api/v1/travels \
    FAULT_ERROR_CODE=INTERNAL_SERVER_ERROR \
    FAULT_HTTP_STATUS=500

EXPOSE 8080 9091
ENTRYPOINT ["python", "/app/server.py"]
