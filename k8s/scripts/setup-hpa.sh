#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

NAMESPACE="travel-planner"

for bin in kubectl; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: $bin 명령을 찾을 수 없다." >&2
    exit 1
  fi
done

if ! kubectl get deployment backend -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "error: backend deployment가 없다. 먼저 ./k8s/scripts/setup.sh 를 실행해라." >&2
  exit 1
fi

echo "-> metrics-server apply (kind 전용 패치 포함)"
kubectl apply -f "$K8S_DIR/metrics-server.yaml"

echo "-> metrics-server Ready 대기"
kubectl rollout status deployment/metrics-server -n kube-system --timeout=120s

echo "-> hpa apply"
kubectl apply -f "$K8S_DIR/hpa.yaml"

echo "-> 첫 메트릭 수집 대기 (최대 60초, 알려진 지연)"
for i in $(seq 1 12); do
  if kubectl top pods -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "-> 메트릭 수집 확인됨"
    break
  fi
  sleep 5
done

echo "-> 완료. 다음 명령으로 상태를 확인해라:"
echo "   kubectl top pods -n $NAMESPACE"
echo "   kubectl get hpa -n $NAMESPACE -w"
