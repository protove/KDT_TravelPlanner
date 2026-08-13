// 환경변수로 모든 실행 조건을 주입한다 (BASE_URL, 계정 정보, 부하 프로필 등).
// 하드코딩된 기본값은 로컬 smoke 실행 편의를 위한 것일 뿐, AWS 실행에서는
// 반드시 env로 덮어써야 한다. (K6_LOAD_TEST_TOOL_DECISION.md 8.1 인증 원칙 참고)

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

// Smoke/Normal 등 실행 단계를 구분하는 태그. summary.json·metadata.json,
// Grafana 쪽 tag와 맞춰 나중에 결과를 필터링할 때 쓴다.
export const SCENARIO_TAG = __ENV.SCENARIO_TAG || 'local-smoke';

// evidence/load-tests/<run-id>/ 디렉터리명과 동일하게 맞춰서 실행 스크립트(run-smoke.sh)가 주입한다.
export const RUN_ID = __ENV.RUN_ID || `${Date.now()}`;

// B-01에서 최대 안정 RPS를 찾기 전까지, baseline.js는 이 값을 로컬 dry-run용
// 가정치로만 사용한다. 절대 발표용 SLO 근거로 쓰지 않는다.
export const TARGET_RPS = Number(__ENV.TARGET_RPS || 5);
