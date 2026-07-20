#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
	echo "Usage: $0 <dev|prod>" >&2
}

if [[ $# -ne 1 ]]; then
	usage
	exit 2
fi

profile="$1"
case "$profile" in
	dev)
		env_file=".env.dev.example"
		compose_files=(-f compose.yml -f compose.dev.yml -f compose.monitoring.yml -f compose.monitoring.dev.yml)
		;;
	prod)
		env_file=".env.prod.example"
		compose_files=(-f compose.yml -f compose.monitoring.yml)
		;;
	*)
		usage
		exit 2
		;;
esac

script_directory="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_directory/.." && pwd)"
cd "$repository_root"

run_id="${GITHUB_RUN_ID:-local-$$}"
run_attempt="${GITHUB_RUN_ATTEMPT:-1}"
project_name="travel-diary-monitoring-ci-${profile}-${run_id}-${run_attempt}"
artifact_directory="${MONITORING_SMOKE_ARTIFACT_DIR:-${RUNNER_TEMP:-/tmp}/travel-diary-monitoring-smoke}"
artifact_file="$artifact_directory/${profile}.log"
request_id="monitoring-ci-${profile}-${run_id}-${run_attempt}"

mkdir -p "$artifact_directory"

export COMPOSE_PROJECT_NAME="$project_name"
export FRONTEND_PORT=0
export BACKEND_PORT=0
export MANAGEMENT_PORT=0
export PROMETHEUS_PORT=0
export LOKI_PORT=0
export ALLOY_PORT=0
export GRAFANA_PORT=0
export GRAFANA_ADMIN_USER="monitoring-ci-admin"
export GRAFANA_ADMIN_PASSWORD="monitoring-ci-only-${profile}-${run_id}-${run_attempt}"
export JWT_SECRET="monitoring-ci-only-jwt-secret-${profile}-${run_id}-${run_attempt}-32bytes"

compose() {
	docker compose --env-file "$env_file" "${compose_files[@]}" "$@"
}

collect_evidence() {
	{
		echo "profile=$profile"
		echo "project=$project_name"
		echo "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		echo
		echo "[compose ps]"
		compose ps --all || true
		echo
		echo "[selected service logs]"
		compose logs --no-color --timestamps \
			backend postgres redis prometheus loki alloy grafana || true
	} >"$artifact_file" 2>&1
}

cleanup() {
	status=$?
	trap - EXIT INT TERM
	if [[ $status -ne 0 ]]; then
		collect_evidence
	fi
	compose down -v --remove-orphans >/dev/null 2>&1 || true
	if [[ $status -ne 0 ]]; then
		echo "Monitoring smoke failed. Sanitized evidence: $artifact_file" >&2
	fi
	exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for() {
	description="$1"
	shift
	for attempt in $(seq 1 30); do
		if "$@"; then
			echo "Verified: $description"
			return 0
		fi
		if [[ $attempt -lt 30 ]]; then
			sleep 4
		fi
	done
	echo "Timed out: $description" >&2
	return 1
}

service_url() {
	service="$1"
	container_port="$2"
	address="$(compose port "$service" "$container_port" | tail -n 1)"
	if [[ -z "$address" ]]; then
		echo "No host port found for ${service}:${container_port}" >&2
		return 1
	fi
	printf 'http://%s' "$address"
}

grafana_get() {
	path="$1"
	curl --fail --silent --show-error \
		--user "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}" \
		"${grafana_url}${path}"
}

grafana_health_is_ready() {
	grafana_get "/api/health" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
raise SystemExit(0 if payload.get("database") == "ok" else 1)
' >/dev/null 2>&1
}

grafana_datasource_exists() {
	uid="$1"
	grafana_get "/api/datasources/uid/${uid}" | python3 -c '
import json, sys
expected = sys.argv[1]
payload = json.load(sys.stdin)
raise SystemExit(0 if payload.get("uid") == expected else 1)
' "$uid" >/dev/null 2>&1
}

grafana_datasource_is_healthy() {
	uid="$1"
	grafana_get "/api/datasources/uid/${uid}/health" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
status = str(payload.get("status", "")).upper()
raise SystemExit(0 if status in {"OK", "SUCCESS"} else 1)
' >/dev/null 2>&1
}

grafana_dashboard_exists() {
	grafana_get "/api/dashboards/uid/travelplanner-backend-overview" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
dashboard = payload.get("dashboard", {})
meta = payload.get("meta", {})
valid = dashboard.get("uid") == "travelplanner-backend-overview" and meta.get("provisioned") is True
raise SystemExit(0 if valid else 1)
' >/dev/null 2>&1
}

prometheus_targets_are_up() {
	grafana_get "/api/datasources/proxy/uid/prometheus/api/v1/targets?state=active" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
targets = payload.get("data", {}).get("activeTargets", [])
up_jobs = {
    target.get("labels", {}).get("job")
    for target in targets
    if target.get("health") == "up"
}
required = {"backend", "prometheus", "loki", "alloy"}
raise SystemExit(0 if required <= up_jobs else 1)
' >/dev/null 2>&1
}

backend_http_metric_exists() {
	grafana_get "/api/datasources/proxy/uid/prometheus/api/v1/query?query=http_server_requests_seconds_count%7Bjob%3D%22backend%22%7D" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
result = payload.get("data", {}).get("result", [])
raise SystemExit(0 if payload.get("status") == "success" and result else 1)
' >/dev/null 2>&1
}

loki_request_log_exists() {
	encoded_query="%7Bservice%3D%22travel-planner-backend%22%2Cenvironment%3D%22${profile}%22%7D"
	grafana_get "/api/datasources/proxy/uid/loki/loki/api/v1/query_range?query=${encoded_query}&limit=100&direction=backward" | python3 -c '
import json, sys
marker = sys.argv[1]
profile = sys.argv[2]
payload = json.load(sys.stdin)
for result in payload.get("data", {}).get("result", []):
    stream = result.get("stream", {})
    if stream.get("service") != "travel-planner-backend":
        continue
    if stream.get("environment") != profile or not stream.get("level"):
        continue
    if any(marker in line for _, line in result.get("values", [])):
        raise SystemExit(0)
raise SystemExit(1)
' "$request_id" "$profile" >/dev/null 2>&1
}

assert_port_private() {
	service="$1"
	container_port="$2"
	container_id="$(compose ps -q "$service")"
	binding="$(docker inspect --format "{{json (index .NetworkSettings.Ports \"${container_port}/tcp\")}}" "$container_id")"
	if [[ "$binding" != "null" && "$binding" != "[]" ]]; then
		echo "Expected ${service}:${container_port} to remain private, found: $binding" >&2
		return 1
	fi
}

assert_port_bound() {
	service="$1"
	container_port="$2"
	container_id="$(compose ps -q "$service")"
	binding="$(docker inspect --format "{{json (index .NetworkSettings.Ports \"${container_port}/tcp\")}}" "$container_id")"
	if [[ "$binding" == "null" || "$binding" == "[]" ]]; then
		echo "Expected ${service}:${container_port} to have a localhost binding." >&2
		return 1
	fi
}

echo "Starting ${profile} monitoring smoke with project ${project_name}."
compose up --build -d --wait backend prometheus loki alloy grafana

if compose ps --all --services | grep -qx frontend; then
	echo "Frontend must not be created by the monitoring smoke test." >&2
	exit 1
fi

backend_url="$(service_url backend 8080)"
grafana_url="$(service_url grafana 3000)"

curl --fail --silent --show-error \
	--header "X-Request-Id: ${request_id}" \
	"${backend_url}/api/ping" >/dev/null

wait_for "Grafana health" grafana_health_is_ready
wait_for "Prometheus datasource provisioning" grafana_datasource_exists prometheus
wait_for "Loki datasource provisioning" grafana_datasource_exists loki
wait_for "Prometheus datasource health" grafana_datasource_is_healthy prometheus
wait_for "Loki datasource health" grafana_datasource_is_healthy loki
wait_for "Backend Overview dashboard provisioning" grafana_dashboard_exists
wait_for "Prometheus targets backend/prometheus/loki/alloy UP" prometheus_targets_are_up
wait_for "backend HTTP request metric" backend_http_metric_exists
wait_for "request log delivered through Alloy to Loki" loki_request_log_exists

if [[ "$profile" == "prod" ]]; then
	assert_port_private backend 9091
	assert_port_private prometheus 9090
	assert_port_private loki 3100
	assert_port_private alloy 12345
else
	assert_port_bound backend 9091
	assert_port_bound prometheus 9090
	assert_port_bound loki 3100
	assert_port_bound alloy 12345
fi

echo "Monitoring smoke passed for ${profile}."
