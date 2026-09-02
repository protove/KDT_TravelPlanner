#!/usr/bin/env bash
set -euo pipefail

# SSM-side smoke and teardown helper. It is uploaded with a SHA-256 and runs
# only against the exact disposable cluster/Ingress ownership supplied by the
# operator lifecycle wrapper.
umask 077

STAGE=""
BUCKET=""
SMOKE_SCRIPT_KEY=""
EXPECTED_SMOKE_SCRIPT_SHA256=""
CLUSTER_NAME=""
REGION=""
BACKEND_HOSTNAME=""
MONITORING_DNS=""
INGRESS_GROUP="kdt-travelplanner-dev-eks"
EXPECTED_HELPER_SHA256=""
DATABASE_IDENTIFIER=""
REDIS_REPLICATION_GROUP_ID=""
REDIS_ENDPOINT=""
REDIS_PORT=""
REDIS_SECRET_ARN=""
PROFILE_IMAGE_BUCKET=""
OPERATOR_DATA_KEY=""
EXPECTED_OPERATOR_DATA_SHA256=""
WORK_DIR="/var/tmp/travel-planner-dev-eks-lifecycle"
TIMEOUT_SECONDS="${DEV_EKS_LIFECYCLE_REMOTE_TIMEOUT_SECONDS:-900}"
TARGET_HEALTH_TIMEOUT_SECONDS="${DEV_EKS_LIFECYCLE_TARGET_HEALTH_TIMEOUT_SECONDS:-300}"
SMOKE_RAW_FILES=()

usage() {
  cat >&2 <<'USAGE'
Usage: run-dev-eks-lifecycle-remote.sh --stage smoke|cleanup-ingress|cleanup-workload|cleanup-platform \
  --cluster-name <name> --region <region> --work-dir <private-dir> \
  [--bucket <bucket> --smoke-script-key <key> --expected-smoke-script-sha256 <sha256>] \
  [--backend-hostname <hostname> --monitoring-dns <private-dns>] \
  [--ingress-group <group>] [--expected-helper-sha256 <sha256>] \
  [--operator-data-key <s3-key> --expected-operator-data-sha256 <sha256>] \
  [--database-identifier <rds-instance>] [--redis-replication-group-id <replication-group>] \
  [--redis-endpoint <private-tls-endpoint> --redis-port <port> --redis-secret-arn <secret-arn>] \
  [--profile-image-bucket <s3-bucket>]
USAGE
}

die() {
  printf 'stage=%s status=failed reason=%s\n' "${STAGE:-unknown}" "$1" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --stage) STAGE="${2:?missing value for --stage}"; shift 2 ;;
    --bucket) BUCKET="${2:?missing value for --bucket}"; shift 2 ;;
    --smoke-script-key) SMOKE_SCRIPT_KEY="${2:?missing value for --smoke-script-key}"; shift 2 ;;
    --expected-smoke-script-sha256) EXPECTED_SMOKE_SCRIPT_SHA256="${2:?missing value for --expected-smoke-script-sha256}"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="${2:?missing value for --cluster-name}"; shift 2 ;;
    --region) REGION="${2:?missing value for --region}"; shift 2 ;;
    --backend-hostname) BACKEND_HOSTNAME="${2:?missing value for --backend-hostname}"; shift 2 ;;
    --monitoring-dns) MONITORING_DNS="${2:?missing value for --monitoring-dns}"; shift 2 ;;
    --ingress-group) INGRESS_GROUP="${2:?missing value for --ingress-group}"; shift 2 ;;
    --expected-helper-sha256) EXPECTED_HELPER_SHA256="${2:?missing value for --expected-helper-sha256}"; shift 2 ;;
    --database-identifier) DATABASE_IDENTIFIER="${2:?missing value for --database-identifier}"; shift 2 ;;
    --redis-replication-group-id) REDIS_REPLICATION_GROUP_ID="${2:?missing value for --redis-replication-group-id}"; shift 2 ;;
    --redis-endpoint) REDIS_ENDPOINT="${2:?missing value for --redis-endpoint}"; shift 2 ;;
    --redis-port) REDIS_PORT="${2:?missing value for --redis-port}"; shift 2 ;;
    --redis-secret-arn) REDIS_SECRET_ARN="${2:?missing value for --redis-secret-arn}"; shift 2 ;;
    --profile-image-bucket) PROFILE_IMAGE_BUCKET="${2:?missing value for --profile-image-bucket}"; shift 2 ;;
    --operator-data-key) OPERATOR_DATA_KEY="${2:?missing value for --operator-data-key}"; shift 2 ;;
    --expected-operator-data-sha256) EXPECTED_OPERATOR_DATA_SHA256="${2:?missing value for --expected-operator-data-sha256}"; shift 2 ;;
    --work-dir) WORK_DIR="${2:?missing value for --work-dir}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument" ;;
  esac
done

[[ "$STAGE" =~ ^(smoke|cleanup-ingress|cleanup-workload|cleanup-platform)$ ]] || die "invalid stage"
[[ "$CLUSTER_NAME" =~ ^[a-z0-9][a-z0-9-]{0,99}$ ]] || die "cluster name is invalid"
[[ "$REGION" =~ ^[a-z0-9-]+$ ]] || die "region is invalid"
[[ "$INGRESS_GROUP" == "kdt-travelplanner-dev-eks" ]] || die "ingress group is outside the approved scope"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$TIMEOUT_SECONDS" -le 3600 ]] || die "remote timeout is invalid"
[[ "$TARGET_HEALTH_TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$TARGET_HEALTH_TIMEOUT_SECONDS" -le 900 ]] || die "target health timeout is invalid"
if [[ -n "$EXPECTED_HELPER_SHA256" ]]; then
  [[ "$EXPECTED_HELPER_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "helper checksum is invalid"
  [[ "$(sha256sum "${BASH_SOURCE[0]}" | awk '{print $1}')" == "$EXPECTED_HELPER_SHA256" ]] || die "helper checksum mismatch"
fi
if [[ "$STAGE" == smoke ]]; then
  [[ -n "$BUCKET" && -n "$SMOKE_SCRIPT_KEY" && -n "$EXPECTED_SMOKE_SCRIPT_SHA256" ]] || die "smoke script transport is incomplete"
  [[ -n "$DATABASE_IDENTIFIER" && -n "$REDIS_REPLICATION_GROUP_ID" && -n "$REDIS_ENDPOINT" && -n "$REDIS_PORT" && -n "$REDIS_SECRET_ARN" && -n "$PROFILE_IMAGE_BUCKET" ]] || die "smoke runtime identity inputs are incomplete"
  [[ "$DATABASE_IDENTIFIER" =~ ^[a-zA-Z][a-zA-Z0-9-]{0,62}$ ]] || die "database identifier is invalid"
  [[ "$REDIS_REPLICATION_GROUP_ID" =~ ^[a-zA-Z][a-zA-Z0-9-]{0,62}$ ]] || die "redis replication group id is invalid"
  [[ "$REDIS_ENDPOINT" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "redis endpoint is invalid"
  [[ "$REDIS_PORT" =~ ^[0-9]+$ && "$REDIS_PORT" -ge 1 && "$REDIS_PORT" -le 65535 ]] || die "redis port is invalid"
  [[ "$REDIS_SECRET_ARN" =~ ^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:.+$ ]] || die "redis secret ARN is invalid"
  [[ "$PROFILE_IMAGE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die "profile image bucket is invalid"
  [[ "$EXPECTED_SMOKE_SCRIPT_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "smoke script checksum is invalid"
  [[ "$OPERATOR_DATA_KEY" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$ && "$OPERATOR_DATA_KEY" != *".."* && "$OPERATOR_DATA_KEY" != *"//"* ]] || die "operator smoke evidence key is invalid"
  [[ "$EXPECTED_OPERATOR_DATA_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "operator smoke evidence checksum is invalid"
  [[ "$BACKEND_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "backend hostname is invalid"
  [[ "$MONITORING_DNS" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || die "monitoring DNS is invalid"
fi

for command_name in aws jq kubectl python3 sha256sum mktemp; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
done
if [[ "$STAGE" == smoke ]]; then
  for command_name in curl getent; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
  done
fi

mkdir -p "$WORK_DIR"
chmod 0700 "$WORK_DIR"
KUBECONFIG_PATH="$WORK_DIR/kubeconfig"
export KUBECONFIG="$KUBECONFIG_PATH"
LOG_FILE="$WORK_DIR/lifecycle-${STAGE}.log"
SUMMARY_FILE="$WORK_DIR/lifecycle-${STAGE}-summary.json"
cleanup_remote() {
  local path exit_status=$?
  for path in "${SMOKE_RAW_FILES[@]}"; do
    [[ -z "$path" ]] || rm -f -- "$path"
  done
  rm -f -- "$KUBECONFIG_PATH"
  if [[ "$exit_status" -eq 0 ]]; then
    rm -f -- "$LOG_FILE"
  else
    chmod 0600 "$LOG_FILE" 2>/dev/null || true
  fi
}
trap cleanup_remote EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

update_kubeconfig() {
  aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --kubeconfig "$KUBECONFIG_PATH" >"$LOG_FILE" 2>&1 || die "kubeconfig update failed"
  kubectl --kubeconfig "$KUBECONFIG_PATH" get --request-timeout=30s --raw=/version >>"$LOG_FILE" 2>&1 || die "cluster identity check failed"
}

cleanup_ingress() {
  update_kubeconfig
  kubectl delete ingress backend --namespace travel-planner --ignore-not-found --wait=false >>"$LOG_FILE" 2>&1 || die "Ingress delete request failed"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    if ! kubectl get --request-timeout=30s ingress backend --namespace travel-planner >/dev/null 2>&1; then
      break
    fi
    sleep 5
  done
  if kubectl get --request-timeout=30s ingress backend --namespace travel-planner >/dev/null 2>&1; then
    kubectl patch ingress backend --namespace travel-planner --type merge --patch '{"metadata":{"finalizers":[]}}' >>"$LOG_FILE" 2>&1 || die "exact Ingress finalizer removal failed"
    deadline=$((SECONDS + TIMEOUT_SECONDS))
    while ((SECONDS < deadline)); do
      kubectl get --request-timeout=30s ingress backend --namespace travel-planner >/dev/null 2>&1 || break
      sleep 5
    done
  fi
  kubectl get --request-timeout=30s ingress backend --namespace travel-planner >/dev/null 2>&1 && die "Ingress remains after finalizer removal"
  jq -n --arg stage "$STAGE" '{schema_version:"dev-eks-lifecycle-remote/v1",stage:$stage,status:"success",ingress_deleted:true,owned_alb_cleanup_deferred:true}' >"$SUMMARY_FILE"
  printf 'stage=%s status=success\n' "$STAGE"
}

cleanup_workload() {
  update_kubeconfig
  kubectl delete namespace travel-planner-monitoring --ignore-not-found --wait=true --timeout="${TIMEOUT_SECONDS}s" >>"$LOG_FILE" 2>&1 || die "monitoring namespace deletion failed"
  kubectl delete namespace travel-planner --ignore-not-found --wait=true --timeout="${TIMEOUT_SECONDS}s" >>"$LOG_FILE" 2>&1 || die "Backend namespace deletion failed"
  jq -n --arg stage "$STAGE" '{schema_version:"dev-eks-lifecycle-remote/v1",stage:$stage,status:"success",deleted_namespaces:["travel-planner","travel-planner-monitoring"]}' >"$SUMMARY_FILE"
  printf 'stage=%s status=success\n' "$STAGE"
}

cleanup_platform() {
  update_kubeconfig
  if [[ -d "$WORK_DIR/rendered/overlays/dev-eks/platform" ]]; then
    kubectl delete --kustomize "$WORK_DIR/rendered/overlays/dev-eks/platform" --ignore-not-found --wait=true --timeout="${TIMEOUT_SECONDS}s" >>"$LOG_FILE" 2>&1 || die "platform deletion failed"
  fi
  kubectl delete ingressclass alb --ignore-not-found --wait=true --timeout="${TIMEOUT_SECONDS}s" >>"$LOG_FILE" 2>&1 || die "IngressClass deletion failed"
  kubectl delete crd targetgroupbindings.elbv2.k8s.aws ingressclassparams.elbv2.k8s.aws --ignore-not-found --wait=true --timeout="${TIMEOUT_SECONDS}s" >>"$LOG_FILE" 2>&1 || die "AWS Load Balancer Controller CRD deletion failed"
  jq -n --arg stage "$STAGE" '{schema_version:"dev-eks-lifecycle-remote/v1",stage:$stage,status:"success",platform_deleted:true}' >"$SUMMARY_FILE"
  printf 'stage=%s status=success\n' "$STAGE"
}

backend_exec() {
  kubectl exec --request-timeout=30s deployment/backend --namespace travel-planner -- sh -c "$1"
}

backend_exec_http_with_retry() {
  local command="$1" output="$2" failure_reason="$3" attempts="${4:-24}" attempt
  : >"$output"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if backend_exec "$command" >"$output" 2>>"$LOG_FILE" && [[ -s "$output" ]]; then
      return 0
    fi
    printf 'phase=smoke status=dependency_retry target=%s attempt=%s/%s\n' "$failure_reason" "$attempt" "$attempts" >>"$LOG_FILE"
    sleep 5
  done
  die "$failure_reason"
}

backend_exec_loki_with_retry() {
  local command="$1" output="$2" failure_reason="$3" attempts="${4:-24}" attempt
  : >"$output"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if backend_exec "$command" >"$output" 2>>"$LOG_FILE" \
      && jq -e '.status == "success" and ((.data.result // []) | type == "array" and length > 0)' "$output" >/dev/null; then
      return 0
    fi
    printf 'phase=smoke status=dependency_retry target=%s attempt=%s/%s\n' "$failure_reason" "$attempt" "$attempts" >>"$LOG_FILE"
    sleep 5
  done
  die "$failure_reason"
}

smoke() {
  update_kubeconfig
  local fixture="$WORK_DIR/observability-fixture.json" data="$WORK_DIR/data-evidence.json" operator_data="$WORK_DIR/operator-data-evidence.json" smoke_script="$WORK_DIR/verify-eks-observability-smoke.py" ingress_json hostname backend_json overall_json prometheus_json loki_json flyway_log private_dns_verified redis_authenticated flyway_success flyway_evidence_source backend_deployment_json alloy_daemonset_json ksm_deployment_json hpa_json metrics_json backend_ready monitoring_ready metrics_hpa_ready now_epoch loki_start_ns loki_end_ns
  mkdir -p "$WORK_DIR/smoke"
  ingress_json="$WORK_DIR/smoke/ingress.json"
  SMOKE_RAW_FILES=("$ingress_json")
  kubectl get --request-timeout=30s ingress backend --namespace travel-planner --output json >"$ingress_json" 2>>"$LOG_FILE" || die "Ingress is missing for smoke"
  hostname="$(jq -r '[.status.loadBalancer.ingress[]?.hostname // empty] | if length == 1 then .[0] else empty end' "$ingress_json")"
  [[ "$hostname" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+elb\.amazonaws\.com$ ]] || die "Ingress hostname is invalid for smoke"
  backend_deployment_json="$WORK_DIR/smoke/backend-deployment.json"
  alloy_daemonset_json="$WORK_DIR/smoke/alloy-daemonset.json"
  ksm_deployment_json="$WORK_DIR/smoke/ksm-deployment.json"
  hpa_json="$WORK_DIR/smoke/backend-hpa.json"
  metrics_json="$WORK_DIR/smoke/metrics.json"
  SMOKE_RAW_FILES+=("$backend_deployment_json" "$alloy_daemonset_json" "$ksm_deployment_json" "$hpa_json" "$metrics_json")
  kubectl get deployment backend --namespace travel-planner --output json >"$backend_deployment_json" 2>>"$LOG_FILE" || die "Backend Deployment status probe failed"
  kubectl get daemonset alloy --namespace travel-planner-monitoring --output json >"$alloy_daemonset_json" 2>>"$LOG_FILE" || die "Alloy DaemonSet status probe failed"
  kubectl get deployment kube-state-metrics --namespace travel-planner-monitoring --output json >"$ksm_deployment_json" 2>>"$LOG_FILE" || die "KSM Deployment status probe failed"
  jq -e '(.status.readyReplicas // 0) == 2 and (.status.availableReplicas // 0) == 2 and (.status.updatedReplicas // 0) == 2' "$backend_deployment_json" >/dev/null || die "Backend does not have two Ready replicas"
  backend_ready=true
  jq -e '(.status.desiredNumberScheduled // 0) == 2 and (.status.numberReady // 0) == 2 and (.status.updatedNumberScheduled // 0) == 2' "$alloy_daemonset_json" >/dev/null || die "Alloy DaemonSet is not Ready on both nodes"
  jq -e '(.status.readyReplicas // 0) == 1 and (.status.availableReplicas // 0) == 1' "$ksm_deployment_json" >/dev/null || die "KSM is not Ready"
  monitoring_ready=true
  metrics_hpa_ready=false
  for _ in $(seq 1 24); do
    if kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/travel-planner/pods >"$metrics_json" 2>>"$LOG_FILE" \
      && kubectl get hpa backend --namespace travel-planner --output json >"$hpa_json" 2>>"$LOG_FILE" \
      && jq -e '(.items | length) > 0' "$metrics_json" >/dev/null \
      && jq -e '([.status.currentMetrics[]?.resource.current.averageUtilization] | any(type == "number"))' "$hpa_json" >/dev/null; then
      metrics_hpa_ready=true
      break
    fi
    sleep 5
  done
  [[ "$metrics_hpa_ready" == true ]] || die "metrics API or HPA CPU metrics are not Ready"
  backend_json="$WORK_DIR/smoke/backend.json"
  overall_json="$WORK_DIR/smoke/overall.json"
  prometheus_json="$WORK_DIR/smoke/prometheus.json"
  loki_json="$WORK_DIR/smoke/loki.json"
  SMOKE_RAW_FILES+=("$backend_json" "$overall_json" "$prometheus_json" "$loki_json" "$data" "$operator_data" "$fixture" "$smoke_script" "$WORK_DIR/smoke/public-ping.json" "$WORK_DIR/smoke-report.json")
  backend_exec 'if command -v wget >/dev/null 2>&1; then wget -qO- http://127.0.0.1:9091/actuator/health/readiness; else exit 42; fi' >"$backend_json" 2>>"$LOG_FILE" || die "Backend readiness probe failed"
  backend_exec 'if command -v wget >/dev/null 2>&1; then wget -qO- http://127.0.0.1:9091/actuator/health; else exit 42; fi' >"$overall_json" 2>>"$LOG_FILE" || die "Backend overall health probe failed"
  jq -e '.status == "UP"' "$backend_json" >/dev/null || die "Backend readiness is not UP"
  jq -e '.status == "UP"' "$overall_json" >/dev/null || die "Backend overall health is not UP"
  getent hosts "$MONITORING_DNS" >/dev/null 2>>"$LOG_FILE" || die "Monitoring private DNS did not resolve"
  private_dns_verified=true
  curl --fail --silent --show-error --connect-timeout 10 --max-time 30 --connect-to "$BACKEND_HOSTNAME:443:$hostname:443" "https://$BACKEND_HOSTNAME/api/ping" >"$WORK_DIR/smoke/public-ping.json" 2>>"$LOG_FILE" || die "ALB HTTPS Backend ping failed"
  # The public ALB ping intentionally validates the external path, but an ALB
  # request can land on only one replica.  Probe every Ready Backend Pod on its
  # loopback so the shared structured-file/Alloy pipeline produces a fresh
  # event for each replica before the bounded Loki freshness query below.
  local backend_pods pod_count pod
  backend_pods="$(kubectl get pods --request-timeout=30s --namespace travel-planner --selector app.kubernetes.io/name=travel-planner-backend --field-selector=status.phase=Running --output jsonpath='{.items[*].metadata.name}')"
  pod_count="$(wc -w <<<"$backend_pods" | tr -d ' ')"
  [[ "$pod_count" == "2" ]] || die "Backend does not expose two Running Pods for log freshness"
  for pod in $backend_pods; do
    kubectl exec --request-timeout=30s "$pod" --namespace travel-planner --container backend -- sh -c 'if command -v wget >/dev/null 2>&1; then wget -qO /dev/null http://127.0.0.1:8080/api/ping; else exit 42; fi' >>"$LOG_FILE" 2>&1 || die "Backend per-Pod log freshness probe failed"
  done
  backend_exec_http_with_retry "if command -v wget >/dev/null 2>&1; then wget -qO- 'http://$MONITORING_DNS:9090/api/v1/query?query=up%7Benvironment%3D%22dev-eks%22%2Cplatform%3D%22eks%22%7D'; else exit 42; fi" "$prometheus_json" "Prometheus query failed"
  # Query a bounded recent window after the public ping above has generated a
  # fresh Backend log entry.  The verifier still enforces its 180-second age
  # limit, so an old cached Loki stream cannot satisfy this smoke.
  now_epoch="$(date +%s)"
  loki_start_ns="$(( (now_epoch - 180) * 1000000000 ))"
  loki_end_ns="$(( now_epoch * 1000000000 ))"
  backend_exec_loki_with_retry "if command -v wget >/dev/null 2>&1; then wget -qO- 'http://$MONITORING_DNS:3100/loki/api/v1/query_range?query=%7Bservice%3D%22travel-planner-backend%22%2Cenvironment%3D%22dev-eks%22%7D&start=$loki_start_ns&end=$loki_end_ns&limit=20&direction=backward'; else exit 42; fi" "$loki_json" "Loki query failed"
  kubectl get --request-timeout=30s secret backend-secret --namespace travel-planner --output json | jq -e '(.data | keys | sort) == ["GOOGLE_MAPS_API_KEY","GOOGLE_OAUTH_CLIENT_ID","GOOGLE_OAUTH_CLIENT_SECRET","JWT_SECRET","NAVER_OAUTH_CLIENT_ID","NAVER_OAUTH_CLIENT_SECRET","SPRING_DATASOURCE_PASSWORD","SPRING_DATASOURCE_USERNAME","SPRING_DATA_REDIS_PASSWORD"]' >/dev/null 2>>"$LOG_FILE" || die "Backend Secret key-set smoke failed"
  flyway_log="$WORK_DIR/smoke/flyway.log"
  SMOKE_RAW_FILES+=("$flyway_log")
  kubectl logs --request-timeout=30s deployment/backend --namespace travel-planner --since=30m >"$flyway_log" 2>>"$LOG_FILE" || die "Backend Flyway log probe failed"
  # The production Logback profile intentionally keeps the root level at
  # WARN, so Flyway INFO lines are not emitted to kubectl logs.  Include the
  # configured structured file when it is readable, then use the two already
  # validated Actuator probes as an explicit indirect startup-schema guard.
  kubectl exec --request-timeout=30s deployment/backend --namespace travel-planner --container backend -- cat /var/log/travel-planner/travel-planner.log >>"$flyway_log" 2>>"$LOG_FILE" || true
  flyway_evidence_source="startup-log"
  if ! grep -Eiq 'flyway.*(success|complete|migrat)|successfully (applied|validated).*migrat' "$flyway_log"; then
    jq -e '.status == "UP"' "$backend_json" >/dev/null || die "Flyway indirect evidence readiness guard failed"
    jq -e '.status == "UP"' "$overall_json" >/dev/null || die "Flyway indirect evidence health guard failed"
    printf '%s\n' 'indirect_flyway_evidence=backend-readiness-and-jpa-schema-validation' >"$flyway_log"
    flyway_evidence_source="backend-readiness-jpa-validation"
  fi
  flyway_success=true
  # Spring Boot's overall health includes RedisReactiveHealthIndicator.  This
  # is the authenticated application-path probe from inside the Backend Pod;
  # the Bastion must not attempt a direct Redis network connection because its
  # SG is intentionally limited to AWS/EKS APIs and Kubernetes control-plane
  # access.
  [[ "$(jq -r '.status // empty' "$overall_json")" == UP ]] || die "Redis-backed overall health is not UP"
  redis_authenticated=true
  aws s3 cp "s3://$BUCKET/$OPERATOR_DATA_KEY" "$operator_data" >>"$LOG_FILE" 2>&1 || die "operator cloud smoke evidence download failed"
  [[ "$(sha256sum "$operator_data" | awk '{print $1}')" == "$EXPECTED_OPERATOR_DATA_SHA256" ]] || die "operator cloud smoke evidence checksum mismatch"
  jq -e 'type == "object" and .schema_version == "dev-eks-operator-cloud-smoke/v1" and .status == "success" and .rds_available == true and .redis_available == true and .profile_image_identity == true' "$operator_data" >/dev/null || die "operator cloud smoke evidence is invalid"
  jq -n --slurpfile operator "$operator_data" --argjson dns "$private_dns_verified" --argjson flyway "$flyway_success" --arg flyway_source "$flyway_evidence_source" --argjson redis "$redis_authenticated" '{secret_materialized:true,private_dns_verified:$dns,rds_available:$operator[0].rds_available,flyway_success:$flyway,flyway_evidence_source:$flyway_source,redis_authenticated:$redis,profile_image_identity:$operator[0].profile_image_identity}' >"$data"
  chmod 0600 "$data" "$backend_json" "$overall_json" "$prometheus_json" "$loki_json"
  aws s3 cp "s3://$BUCKET/$SMOKE_SCRIPT_KEY" "$smoke_script" >>"$LOG_FILE" 2>&1 || die "observability verifier download failed"
  [[ "$(sha256sum "$smoke_script" | awk '{print $1}')" == "$EXPECTED_SMOKE_SCRIPT_SHA256" ]] || die "observability verifier checksum mismatch"
  jq -n \
    --slurpfile backend "$backend_json" \
    --slurpfile prometheus "$prometheus_json" \
    --slurpfile loki "$loki_json" \
    --slurpfile data "$data" \
    '{backend:{status:200,payload:$backend[0]},prometheus:{status:200,payload:$prometheus[0]},loki:{status:200,payload:$loki[0]},data:$data[0]}' >"$fixture"
  # The verifier is intentionally run after the fixture is assembled; no response body is emitted.
  python3 "$smoke_script" --fixture "$fixture" --output "$WORK_DIR/smoke-report.json" >/dev/null 2>>"$LOG_FILE" || die "observability smoke verifier failed"
  # Keep only the sanitized stage summary and status line on the Bastion.
  rm -f -- "$ingress_json" "$backend_json" "$overall_json" "$prometheus_json" "$loki_json" "$data" "$fixture" "$smoke_script" "$WORK_DIR/smoke/public-ping.json" "$WORK_DIR/smoke-report.json"
  rmdir "$WORK_DIR/smoke" 2>/dev/null || true
  jq -n --arg stage "$STAGE" --arg hostname "redacted-at-boundary" --argjson backend "$backend_ready" --argjson monitoring "$monitoring_ready" --argjson metrics "$metrics_hpa_ready" '{schema_version:"dev-eks-lifecycle-remote/v1",stage:$stage,status:"success",alb_hostname:$hostname,backend_ready:$backend,monitoring_ready:$monitoring,metrics_hpa_ready:$metrics,overall_health:true,prometheus_fresh:true,loki_fresh:true,secret_key_count:9}' >"$SUMMARY_FILE"
  printf 'stage=%s status=success\n' "$STAGE"
}

case "$STAGE" in
  smoke) smoke ;;
  cleanup-ingress) cleanup_ingress ;;
  cleanup-workload) cleanup_workload ;;
  cleanup-platform) cleanup_platform ;;
esac
