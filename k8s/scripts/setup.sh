#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$K8S_DIR/.." && pwd)"

CLUSTER_NAME="travel-planner-local"
NAMESPACE="travel-planner"
IMAGE_TAG="travel-planner-backend:kind-local"
ENV_FILE="$REPO_ROOT/.env.dev"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found. cp .env.dev.example .env.dev 후 값을 채워라." >&2
  exit 1
fi

for bin in kind kubectl docker; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: $bin 명령을 찾을 수 없다." >&2
    exit 1
  fi
done

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "-> kind cluster '$CLUSTER_NAME' 이미 존재함, 생성 단계 건너뜀"
else
  echo "-> kind cluster 생성: $CLUSTER_NAME"
  kind create cluster --config "$K8S_DIR/kind-config.yaml"
fi

echo "-> backend 이미지 빌드 (target=runner)"
docker build --target runner -t "$IMAGE_TAG" "$REPO_ROOT/backend"

echo "-> kind 노드로 이미지 로드"
kind load docker-image "$IMAGE_TAG" --name "$CLUSTER_NAME"

echo "-> namespace apply"
kubectl apply -f "$K8S_DIR/namespace.yaml"

echo "-> backend-secret 생성 (.env.dev 기준, 재실행 시 갱신)"
kubectl create secret generic backend-secret \
  -n "$NAMESPACE" \
  --from-env-file="$ENV_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "-> postgres/redis apply"
kubectl apply \
  -f "$K8S_DIR/postgres-pvc.yaml" \
  -f "$K8S_DIR/postgres-deployment.yaml" \
  -f "$K8S_DIR/postgres-service.yaml" \
  -f "$K8S_DIR/redis-pvc.yaml" \
  -f "$K8S_DIR/redis-deployment.yaml" \
  -f "$K8S_DIR/redis-service.yaml"

echo "-> postgres/redis Ready 대기"
kubectl rollout status deployment/postgres -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/redis -n "$NAMESPACE" --timeout=120s

echo "-> backend apply"
kubectl apply \
  -f "$K8S_DIR/backend-configmap.yaml" \
  -f "$K8S_DIR/backend-deployment.yaml" \
  -f "$K8S_DIR/backend-service.yaml"

echo "-> backend Ready 대기 (Flyway 마이그레이션 포함, 최대 180초)"
kubectl rollout status deployment/backend -n "$NAMESPACE" --timeout=180s

echo "-> 완료. 다음 명령으로 상태를 확인해라:"
echo "   kubectl get pods -n $NAMESPACE"
echo "   kubectl logs deploy/backend -n $NAMESPACE"
echo "   kubectl port-forward svc/backend 9091:9091 -n $NAMESPACE"
