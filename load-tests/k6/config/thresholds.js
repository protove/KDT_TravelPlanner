// LOAD_TEST_SCENARIOS.md 7장 원칙: "측정 전에 그럴듯한 수치를 임의로 만들지 않는다."
// 아래 값은 EXPERIMENT_SLO_PRE_REGISTRATION.md 3장의 "목표 초안"을 그대로 반영했다.
// SLO_VERSION=v1.0-frozen으로 정식 동결되기 전까지는 안전선일 뿐 최종 합격 기준이 아니다.
// (production-like Compose 보정 → EC2 B-01 정상 분포 확인 → 그제서야 동결하는 순서)
export const draftThresholds = {
  http_req_duration: ['p(95)<500'], // 정상 부하 Core API p95 500ms 이하 (초안)
  http_req_failed: ['rate<0.01'], // 예상하지 않은 오류율 1% 미만 (초안). 의도된 4xx는 check로 별도 집계.
  dropped_iterations: ['count<1'], // constant-arrival-rate가 목표 도착률을 못 채우면 즉시 드러나게.
};

// Smoke 단계는 SLO 판정이 아니라 "스크립트·인증·데이터가 동작하는가"만 확인하는
// 넓은 안전 중단선이다. 여기서 실패하면 SLO 문제가 아니라 셋업 자체를 의심할 것.
export const smokeThresholds = {
  http_req_failed: ['rate<0.5'],
};
