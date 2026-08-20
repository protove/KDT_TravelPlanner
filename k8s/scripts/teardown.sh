#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="travel-planner-local"

if ! command -v kind >/dev/null 2>&1; then
  echo "error: kind 명령을 찾을 수 없다." >&2
  exit 1
fi

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "-> kind cluster 삭제: $CLUSTER_NAME"
  kind delete cluster --name "$CLUSTER_NAME"
else
  echo "-> kind cluster '$CLUSTER_NAME' 없음, 삭제할 게 없음"
fi
