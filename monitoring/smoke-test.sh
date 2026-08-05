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
inbound_request_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
sensitive_sentinel="monitoring-sensitive-${profile}-${run_id}-${run_attempt}"
server_request_id=""

mkdir -p "$artifact_directory"
response_headers_file="$(mktemp "${TMPDIR:-/tmp}/travel-planner-response-headers.XXXXXX")"

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

sanitize_evidence() {
	sed -E \
		-e "s/${inbound_request_id}/[REDACTED_INBOUND_REQUEST_ID]/g" \
		-e "s/${sensitive_sentinel}/[REDACTED_SYNTHETIC_SENTINEL]/g" \
		-e "s/${GRAFANA_ADMIN_PASSWORD}/[REDACTED_GRAFANA_ADMIN_PASSWORD]/g" \
		-e "s/${JWT_SECRET}/[REDACTED_JWT_SECRET]/g" \
		-e 's/(Using generated security password:).*/\1 [REDACTED_GENERATED_PASSWORD]/g'
}

assert_evidence_sanitizer() {
	generated_password_probe="monitoring-generated-password-probe"
	sanitized_probe="$({
		echo "Using generated security password: $generated_password_probe"
		echo "$GRAFANA_ADMIN_PASSWORD"
		echo "$JWT_SECRET"
	} | sanitize_evidence)"

	if [[ "$sanitized_probe" == *"$generated_password_probe"* \
		|| "$sanitized_probe" == *"$GRAFANA_ADMIN_PASSWORD"* \
		|| "$sanitized_probe" == *"$JWT_SECRET"* ]]; then
		echo "Monitoring evidence sanitizer left a credential value unchanged." >&2
		return 1
	fi
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
			backend postgres redis prometheus loki alloy grafana \
			| sanitize_evidence \
			|| true
	} >"$artifact_file" 2>&1
}

cleanup() {
	status=$?
	trap - EXIT INT TERM
	if [[ $status -ne 0 ]]; then
		collect_evidence
	fi
	rm -f "$response_headers_file"
	compose down -v --remove-orphans >/dev/null 2>&1 || true
	if [[ $status -ne 0 ]]; then
		echo "Monitoring smoke failed. Sanitized evidence: $artifact_file" >&2
	fi
	exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

assert_evidence_sanitizer

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
request_id = sys.argv[1]
profile = sys.argv[2]
payload = json.load(sys.stdin)
for result in payload.get("data", {}).get("result", []):
    stream = result.get("stream", {})
    if set(stream) != {"service", "environment", "level"}:
        continue
    if stream.get("service") != "travel-planner-backend":
        continue
    if stream.get("environment") != profile or not stream.get("level"):
        continue
    for value in result.get("values", []):
        if len(value) < 2:
            continue
        line = value[1]
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = event.get("status")
        duration_ms = event.get("durationMs")
        valid = (
            event.get("event") == "HTTP_REQUEST_COMPLETED"
            and event.get("requestId") == request_id
            and event.get("method") == "GET"
            and event.get("route") == "/api/ping"
            and isinstance(status, int) and not isinstance(status, bool) and status == 200
            and isinstance(duration_ms, int) and not isinstance(duration_ms, bool) and duration_ms >= 0
            and event.get("outcome") == "SUCCESS"
        )
        if valid:
            raise SystemExit(0)
raise SystemExit(1)
' "$server_request_id" "$profile" >/dev/null 2>&1
}

loki_sensitive_values_are_absent() {
	encoded_query="%7Bservice%3D%22travel-planner-backend%22%2Cenvironment%3D%22${profile}%22%7D"
	grafana_get "/api/datasources/proxy/uid/loki/loki/api/v1/query_range?query=${encoded_query}&limit=100&direction=backward" | python3 -c '
import json, sys
forbidden_values = sys.argv[1:]
payload = json.load(sys.stdin)
serialized = json.dumps(payload, ensure_ascii=False)
raise SystemExit(1 if any(value in serialized for value in forbidden_values) else 0)
' "$inbound_request_id" "$sensitive_sentinel" >/dev/null 2>&1
}

assert_backend_file_excludes_sensitive_values() {
	log_file="/var/log/travel-planner/travel-planner.log"
	if ! compose exec -T backend test -s "$log_file"; then
		echo "Expected a non-empty structured backend log file." >&2
		return 1
	fi
	if compose exec -T backend grep -F \
		-e "$inbound_request_id" \
		-e "$sensitive_sentinel" \
		-e "Using generated security password" \
		"$log_file" >/dev/null; then
		echo "Sensitive synthetic input reached the backend log file." >&2
		return 1
	fi
}

assert_profile_console_policy() {
	backend_stdout="$(compose logs --no-color backend)"
	if [[ "$backend_stdout" == *"$inbound_request_id"* \
		|| "$backend_stdout" == *"$sensitive_sentinel"* \
		|| "$backend_stdout" == *"Using generated security password"* ]]; then
		echo "Sensitive synthetic input reached backend stdout." >&2
		return 1
	fi
	if [[ "$profile" == "prod" ]]; then
		if [[ "$backend_stdout" == *"$server_request_id"* || "$backend_stdout" == *"HTTP_REQUEST_COMPLETED"* ]]; then
			echo "Production request logs must not be written to stdout." >&2
			return 1
		fi
	elif [[ "$backend_stdout" != *"$server_request_id"* || "$backend_stdout" != *"HTTP_REQUEST_COMPLETED"* ]]; then
		echo "Development request logs must remain visible on stdout." >&2
		return 1
	fi
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
	--dump-header "$response_headers_file" \
	--header "X-Request-Id: ${inbound_request_id}" \
	--header "X-Logging-Sentinel: ${sensitive_sentinel}" \
	--cookie "monitoringSentinel=${sensitive_sentinel}" \
	"${backend_url}/api/ping?code=${sensitive_sentinel}" >/dev/null

server_request_id="$(tr -d '\r' <"$response_headers_file" \
	| awk -F ': *' 'tolower($1) == "x-request-id" { print $2 }' \
	| tail -n 1)"
if [[ -z "$server_request_id" ]]; then
	echo "Backend response did not include X-Request-Id." >&2
	exit 1
fi
if [[ "$server_request_id" == "$inbound_request_id" ]]; then
	echo "Backend trusted the inbound X-Request-Id instead of issuing a server ID." >&2
	exit 1
fi
python3 -c '
import sys, uuid
value = sys.argv[1]
parsed = uuid.UUID(value)
raise SystemExit(0 if parsed.version == 4 and str(parsed) == value.lower() else 1)
' "$server_request_id"

wait_for "Grafana health" grafana_health_is_ready
wait_for "Prometheus datasource provisioning" grafana_datasource_exists prometheus
wait_for "Loki datasource provisioning" grafana_datasource_exists loki
wait_for "Prometheus datasource health" grafana_datasource_is_healthy prometheus
wait_for "Loki datasource health" grafana_datasource_is_healthy loki
wait_for "Backend Overview dashboard provisioning" grafana_dashboard_exists
wait_for "Prometheus targets backend/prometheus/loki/alloy UP" prometheus_targets_are_up
wait_for "backend HTTP request metric" backend_http_metric_exists
wait_for "request log delivered through Alloy to Loki" loki_request_log_exists
wait_for "sensitive synthetic values absent from Loki" loki_sensitive_values_are_absent
assert_backend_file_excludes_sensitive_values
assert_profile_console_policy

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
