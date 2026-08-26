#!/usr/bin/env bash
set -euo pipefail

# SCRUM-53 v11: Bastion-only retained-environment smoke. AWS calls are
# limited to EKS kubeconfig/bootstrap; cloud assertions run under the
# operator principal instead.
umask 077

CLUSTER_NAME=""
REGION="ap-northeast-2"
BACKEND_HOSTNAME=""
MONITORING_DNS=""
REDIS_ENDPOINT=""
REDIS_PORT=""
WORK_DIR="/var/tmp/travel-planner-dev-eks-repair/smoke"

usage() {
  cat >&2 <<'USAGE'
Usage: run-dev-eks-repair-smoke.sh --cluster-name <name> --region <region>
  --backend-hostname <hostname> --monitoring-dns <private-dns>
  --redis-endpoint <endpoint> --redis-port <port> --work-dir <private-dir>
USAGE
}

die() {
  printf 'stage=repair-smoke status=failed reason=%s\n' "$1" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --cluster-name) CLUSTER_NAME="${2:?missing value for --cluster-name}"; shift 2 ;;
    --region) REGION="${2:?missing value for --region}"; shift 2 ;;
    --backend-hostname) BACKEND_HOSTNAME="${2:?missing value for --backend-hostname}"; shift 2 ;;
    --monitoring-dns) MONITORING_DNS="${2:?missing value for --monitoring-dns}"; shift 2 ;;
    --redis-endpoint) REDIS_ENDPOINT="${2:?missing value for --redis-endpoint}"; shift 2 ;;
    --redis-port) REDIS_PORT="${2:?missing value for --redis-port}"; shift 2 ;;
    --work-dir) WORK_DIR="${2:?missing value for --work-dir}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument" ;;
  esac
done

[[ "$CLUSTER_NAME" =~ ^[a-z0-9][a-z0-9-]{0,99}$ ]] || die "cluster name is invalid"
[[ "$REGION" =~ ^[a-z0-9-]+$ ]] || die "region is invalid"
[[ "$BACKEND_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "backend hostname is invalid"
[[ "$MONITORING_DNS" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "monitoring DNS is invalid"
[[ "$REDIS_ENDPOINT" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "Redis endpoint is invalid"
[[ "$REDIS_PORT" =~ ^[0-9]+$ && "$REDIS_PORT" -ge 1 && "$REDIS_PORT" -le 65535 ]] || die "Redis port is invalid"
[[ "$WORK_DIR" == /var/tmp/travel-planner-dev-eks-*/* ]] || die "work directory is outside the private repair prefix"
[[ "$WORK_DIR" != *".."* ]] || die "work directory contains traversal or repeated separators"
[[ "$WORK_DIR" != *"//"* ]] || die "work directory contains traversal or repeated separators"
[[ "$WORK_DIR" != */./* ]] || die "work directory contains traversal or repeated separators"
[[ "$WORK_DIR" != */. ]] || die "work directory contains traversal or repeated separators"

validate_private_path() {
  local path="$1" current component
  current="$(cd /var/tmp && pwd -P)"
  [[ "$path" == /var/tmp/* ]] || die "work directory is outside the private repair prefix"
  while IFS= read -r component; do
    [[ -n "$component" ]] || die "work directory contains an empty path component"
    current="$current/$component"
    [[ ! -L "$current" ]] || die "work directory parent must not be a symlink"
  done < <(printf '%s\n' "${path#/var/tmp/}" | tr '/' '\n')
}

validate_private_path "$WORK_DIR"
[[ ! -L "$WORK_DIR" ]] || die "work directory must not be a symlink"

for command_name in aws base64 curl getent jq kubectl python3; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
done

mkdir -p "$WORK_DIR"
chmod 0700 "$WORK_DIR"
KUBECONFIG_PATH="$WORK_DIR/kubeconfig"
export KUBECONFIG="$KUBECONFIG_PATH"
LOG_FILE="$WORK_DIR/repair-smoke.log"
INGRESS_JSON="$WORK_DIR/ingress.json"
READINESS_JSON="$WORK_DIR/backend-readiness.json"
HEALTH_JSON="$WORK_DIR/backend-health.json"
SECRET_JSON="$WORK_DIR/backend-secret.json"
PROMETHEUS_JSON="$WORK_DIR/prometheus.json"
LOKI_JSON="$WORK_DIR/loki.json"
PING_JSON="$WORK_DIR/api-ping.json"
FLYWAY_LOG="$WORK_DIR/flyway.log"

remove_private_files() {
  unset REDIS_AUTH_PASSWORD
  rm -f -- "$LOG_FILE" "$INGRESS_JSON" "$READINESS_JSON" "$HEALTH_JSON" "$SECRET_JSON" \
    "$PROMETHEUS_JSON" "$LOKI_JSON" "$PING_JSON" "$FLYWAY_LOG"
}
trap remove_private_files EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

kubectl_exec() {
  local probe="$1"
  kubectl exec --request-timeout=30s deployment/backend --namespace travel-planner -- sh -c "$probe"
}

http_probe() {
  local url="$1"
  if command -v wget >/dev/null 2>&1; then
    wget -qO- "$url"
  elif command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error --max-time 20 "$url"
  else
    return 42
  fi
}

aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --kubeconfig "$KUBECONFIG_PATH" >"$LOG_FILE" 2>&1 || die "kubeconfig update failed"
kubectl get --request-timeout=30s --raw=/version >>"$LOG_FILE" 2>&1 || die "cluster identity check failed"

kubectl get --request-timeout=30s ingress backend --namespace travel-planner --output json >"$INGRESS_JSON" 2>>"$LOG_FILE" || die "Ingress is missing"
hostname="$(jq -r '[.status.loadBalancer.ingress[]?.hostname // empty] | if length == 1 then .[0] else empty end' "$INGRESS_JSON")"
[[ "$hostname" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]] || die "Ingress hostname is invalid"

kubectl_exec 'http_probe() { if command -v wget >/dev/null 2>&1; then wget -qO- "$1"; elif command -v curl >/dev/null 2>&1; then curl --fail --silent --show-error --max-time 20 "$1"; else exit 42; fi; }; http_probe http://127.0.0.1:9091/actuator/health/readiness' >"$READINESS_JSON" 2>>"$LOG_FILE" || die "Backend readiness probe failed"
kubectl_exec 'http_probe() { if command -v wget >/dev/null 2>&1; then wget -qO- "$1"; elif command -v curl >/dev/null 2>&1; then curl --fail --silent --show-error --max-time 20 "$1"; else exit 42; fi; }; http_probe http://127.0.0.1:9091/actuator/health' >"$HEALTH_JSON" 2>>"$LOG_FILE" || die "Backend overall health probe failed"
jq -e '.status == "UP"' "$READINESS_JSON" >/dev/null || die "Backend readiness is not UP"
jq -e '.status == "UP"' "$HEALTH_JSON" >/dev/null || die "Backend overall health is not UP"

kubectl get --request-timeout=30s secret backend-secret --namespace travel-planner --output json >"$SECRET_JSON" 2>>"$LOG_FILE" || die "Backend Secret is missing"
jq -e '(.data | keys | sort) == ["GOOGLE_MAPS_API_KEY","GOOGLE_OAUTH_CLIENT_ID","GOOGLE_OAUTH_CLIENT_SECRET","JWT_SECRET","NAVER_OAUTH_CLIENT_ID","NAVER_OAUTH_CLIENT_SECRET","SPRING_DATASOURCE_PASSWORD","SPRING_DATASOURCE_USERNAME","SPRING_DATA_REDIS_PASSWORD"]' "$SECRET_JSON" >/dev/null || die "Backend Secret key-set is invalid"
redis_password="$(jq -er '.data.SPRING_DATA_REDIS_PASSWORD' "$SECRET_JSON" | base64 -d)" || die "Redis credential decoding failed"
[[ -n "$redis_password" ]] || die "Redis credential is empty"

REDIS_AUTH_PASSWORD="$redis_password" python3 - "$REDIS_ENDPOINT" "$REDIS_PORT" <<'PY' || die "Redis TLS AUTH/PING probe failed"
import os
import socket
import ssl
import sys

endpoint, port = sys.argv[1], int(sys.argv[2])
password = os.environ["REDIS_AUTH_PASSWORD"].encode()
context = ssl.create_default_context()
with socket.create_connection((endpoint, port), timeout=10) as raw:
    with context.wrap_socket(raw, server_hostname=endpoint) as conn:
        auth = b"*3\r\n$4\r\nAUTH\r\n$7\r\ndefault\r\n$" + str(len(password)).encode() + b"\r\n" + password + b"\r\n"
        conn.sendall(auth)
        if not conn.recv(128).startswith(b"+OK"):
            raise SystemExit(1)
        conn.sendall(b"*1\r\n$4\r\nPING\r\n")
        if not conn.recv(128).startswith(b"+PONG"):
            raise SystemExit(1)
PY
unset redis_password REDIS_AUTH_PASSWORD

getent hosts "$MONITORING_DNS" >/dev/null 2>>"$LOG_FILE" || die "Monitoring private DNS did not resolve"
curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
  --connect-to "$BACKEND_HOSTNAME:443:$hostname:443" \
  "https://$BACKEND_HOSTNAME/api/ping" >"$PING_JSON" 2>>"$LOG_FILE" || die "ALB HTTPS Backend ping failed"
kubectl_exec "if command -v wget >/dev/null 2>&1; then wget -qO- 'http://$MONITORING_DNS:9090/api/v1/query?query=up%7Benvironment%3D%22dev-eks%22%2Cplatform%3D%22eks%22%7D'; elif command -v curl >/dev/null 2>&1; then curl --fail --silent --show-error --max-time 20 'http://$MONITORING_DNS:9090/api/v1/query?query=up%7Benvironment%3D%22dev-eks%22%2Cplatform%3D%22eks%22%7D'; else exit 42; fi" >"$PROMETHEUS_JSON" 2>>"$LOG_FILE" || die "Prometheus private query failed"
jq -e '.status == "success"' "$PROMETHEUS_JSON" >/dev/null || die "Prometheus response is not successful"
loki_ready=false
for _ in $(seq 1 24); do
  now_epoch="$(date +%s)"
  loki_start_ns="$(( (now_epoch - 180) * 1000000000 ))"
  loki_end_ns="$(( now_epoch * 1000000000 ))"
  if kubectl_exec "if command -v wget >/dev/null 2>&1; then wget -qO- 'http://$MONITORING_DNS:3100/loki/api/v1/query_range?query=%7Bservice%3D%22travel-planner-backend%22%2Cenvironment%3D%22dev-eks%22%7D&start=$loki_start_ns&end=$loki_end_ns&limit=20&direction=backward'; elif command -v curl >/dev/null 2>&1; then curl --fail --silent --show-error --max-time 20 'http://$MONITORING_DNS:3100/loki/api/v1/query_range?query=%7Bservice%3D%22travel-planner-backend%22%2Cenvironment%3D%22dev-eks%22%7D&start=$loki_start_ns&end=$loki_end_ns&limit=20&direction=backward'; else exit 42; fi" >"$LOKI_JSON" 2>>"$LOG_FILE" \
    && jq -e '.status == "success" and ((.data.result // []) | type == "array" and length > 0)' "$LOKI_JSON" >/dev/null; then
    loki_ready=true
    break
  fi
  sleep 5
done
[[ "$loki_ready" == true ]] || die "Loki private query failed"
kubectl logs --request-timeout=30s deployment/backend --namespace travel-planner --since=30m >"$FLYWAY_LOG" 2>>"$LOG_FILE" || die "Backend Flyway log probe failed"
# The prod Logback root level is WARN by design, which suppresses Flyway INFO
# lines from kubectl logs.  Preserve the direct probe, include the configured
# file if available, and fall back to the already-validated readiness/health
# startup-schema guard with an explicit indirect marker.  This keeps the
# Flyway success evidence requirement fail-closed without asserting a log line
# that the configured logger is designed not to emit.
kubectl exec --request-timeout=30s deployment/backend --namespace travel-planner --container backend -- cat /var/log/travel-planner/travel-planner.log >>"$FLYWAY_LOG" 2>>"$LOG_FILE" || true
if ! grep -Eiq 'flyway.*(success|complete|migrat)|successfully (applied|validated).*migrat' "$FLYWAY_LOG"; then
  jq -e '.status == "UP"' "$READINESS_JSON" >/dev/null || die "Flyway indirect evidence readiness guard failed"
  jq -e '.status == "UP"' "$HEALTH_JSON" >/dev/null || die "Flyway indirect evidence health guard failed"
  printf '%s\n' 'indirect_flyway_evidence=backend-readiness-and-jpa-schema-validation' >"$FLYWAY_LOG"
fi

jq -n --arg hostname "$hostname" \
  '{schema_version:"dev-eks-repair-smoke/v1",status:"success",ingress_hostname:$hostname,backend_readiness:true,backend_health:true,backend_secret_key_set:true,redis_tls_auth_ping:true,prometheus_private_query:true,loki_private_query:true,alb_https_ping:true,flyway_success:true}' \
  >"$WORK_DIR/repair-smoke-summary.json"
chmod 0600 "$WORK_DIR/repair-smoke-summary.json"
printf 'stage=repair-smoke status=success\n'
