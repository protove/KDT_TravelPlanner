#!/usr/bin/env bash
set -euo pipefail

# K6_LOAD_TEST_TOOL_DECISION.md 10장 "1일 spike 확정 게이트"용 최소 실행 스크립트.
# production-like Compose가 이미 떠 있다고 가정한다.
#
# 사용법:
#   BASE_URL=http://localhost:8080 ./scripts/run-smoke.sh
#
# Docker Desktop(Mac/Windows)에서는 --network host가 동작하지 않으므로,
# compose 네트워크 이름을 알아내 NETWORK 환경변수로 넘기고
# BASE_URL을 서비스명 기준(예: http://backend:8080)으로 바꿔서 실행할 것.
#   NETWORK=kdt_app-network BASE_URL=http://backend:8080 ./scripts/run-smoke.sh

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="evidence/load-tests/${RUN_ID}"
mkdir -p "${EVIDENCE_DIR}"

COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
K6_VERSION="$(docker run --rm grafana/k6 version | head -n1)"
NETWORK_MODE="${NETWORK:-host}"

echo "Run ID   : ${RUN_ID}"
echo "Commit   : ${COMMIT_SHA}"
echo "k6       : ${K6_VERSION}"
echo "Network  : ${NETWORK_MODE}"
echo "BASE_URL : ${BASE_URL:-http://localhost:8080}"

docker run --rm \
  --network "${NETWORK_MODE}" \
  -e BASE_URL="${BASE_URL:-http://localhost:8080}" \
  -e RUN_ID="${RUN_ID}" \
  -e COMMIT_SHA="${COMMIT_SHA}" \
  -e K6_VERSION="${K6_VERSION}" \
  -e SCENARIO_TAG="local-smoke" \
  -v "$(pwd)/load-tests/k6:/scripts" \
  -w /scripts \
  grafana/k6 run scenarios/smoke.js \
  --out "json=/scripts/raw.json"

# handleSummary()가 k6 작업 디렉터리(/scripts, 즉 load-tests/k6)에 쓴 파일들을
# 이번 실행의 evidence 디렉터리로 옮긴다.
mv load-tests/k6/summary.json "${EVIDENCE_DIR}/summary.json"
mv load-tests/k6/metadata.json "${EVIDENCE_DIR}/metadata.json"
mv load-tests/k6/raw.json "${EVIDENCE_DIR}/raw.json"

echo "증거 저장 위치: ${EVIDENCE_DIR}"
echo "다음: K6_LOAD_TEST_TOOL_DECISION.md 10.2 확정 조건 체크리스트를 대조할 것."
