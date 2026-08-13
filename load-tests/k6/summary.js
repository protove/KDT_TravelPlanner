import { textSummary } from 'https://jslib.k6.io/k6-summary/0.1.0/index.js';
import { RUN_ID, SCENARIO_TAG } from './lib/config.js';

// K6_LOAD_TEST_TOOL_DECISION.md 9장 증거 구조를 그대로 따른다.
// summary.json은 k6 원본 결과, metadata.json은 재현에 필요한 실행 조건이다.
// 둘 다 credential·개인정보를 포함하지 않는다 — lib/auth.js가 애초에
// 응답 body를 로그로 남기지 않으므로 여기서 별도 마스킹은 필요 없다.
export function handleSummary(data, extra) {
  const metadata = {
    runId: RUN_ID,
    scenarioTag: SCENARIO_TAG,
    stage: extra && extra.stage,
    generatedAtUtc: new Date().toISOString(),
    // 아래 값들은 run-smoke.sh(또는 CI 스크립트)가 실행 시점에 env로 주입한다.
    k6Version: __ENV.K6_VERSION || 'unset',
    commitSha: __ENV.COMMIT_SHA || 'unset',
    imageDigest: __ENV.IMAGE_DIGEST || 'unset',
    baseUrl: __ENV.BASE_URL || 'unset',
    note: 'SLO_VERSION 동결 전 draft 실행 — 발표 확정 근거로 사용하지 않음',
  };

  return {
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
    'summary.json': JSON.stringify(data, null, 2),
    'metadata.json': JSON.stringify(metadata, null, 2),
  };
}
