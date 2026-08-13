import { sleep } from 'k6';
import { SCENARIO_TAG } from '../lib/config.js';
import { pickAccount, pickTravelId } from '../lib/data.js';
import { getAccessToken } from '../lib/auth.js';
import { planReadFlow } from '../flows/plan-read.js';
import { timelineWriteFlow } from '../flows/timeline-write.js';
import { smokeThresholds } from '../config/thresholds.js';
import { handleSummary as sharedHandleSummary } from '../summary.js';

// LOAD_TEST_SCENARIOS.md 4장: "Smoke — 스크립트·인증·데이터 확인, 사용자 1~2명, 주요 흐름 1회"
// 이게 바로 K6_LOAD_TEST_TOOL_DECISION.md 10장 "1일 spike 확정 게이트"의 최소 실행 대상이다.
export const options = {
  scenarios: {
    smoke: {
      executor: 'shared-iterations',
      vus: 2,
      iterations: 4,
      maxDuration: '2m',
    },
  },
  thresholds: smokeThresholds,
  tags: { scenario: SCENARIO_TAG, stage: 'smoke' },
};

export default function () {
  const account = pickAccount(__VU);
  const accessToken = getAccessToken(account);
  if (!accessToken) return; // 인증 실패는 check()로 이미 기록됨. 흐름만 조기 종료.

  const travelId = pickTravelId(__VU, __ITER);

  planReadFlow(accessToken, travelId);
  timelineWriteFlow(accessToken, travelId, __VU, __ITER);

  sleep(1);
}

export function handleSummary(data) {
  return sharedHandleSummary(data, { stage: 'smoke' });
}
