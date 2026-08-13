import { sleep } from 'k6';
import { SCENARIO_TAG, TARGET_RPS } from '../lib/config.js';
import { pickAccount, pickTravelId } from '../lib/data.js';
import { getAccessToken } from '../lib/auth.js';
import { planReadFlow } from '../flows/plan-read.js';
import { timelineWriteFlow } from '../flows/timeline-write.js';
import { draftThresholds } from '../config/thresholds.js';
import { handleSummary as sharedHandleSummary } from '../summary.js';

// LOAD_TEST_SCENARIOS.md 4장: "Normal — 정상 운영 기준선, 목표 동시 사용자로 10분"
// K6_LOAD_TEST_TOOL_DECISION.md 5장 권장대로 constant-arrival-rate를 쓴다:
// 서버가 느려져도 설정한 도착률을 유지해야, "부하가 줄어서 좋아 보이는" 착시를 피할 수 있다.
const DURATION = __ENV.DURATION || '10m';

export const options = {
  scenarios: {
    normal_load: {
      executor: 'constant-arrival-rate',
      rate: TARGET_RPS,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: TARGET_RPS * 2,
      maxVUs: TARGET_RPS * 5, // dropped_iterations가 나오면 이 값을 늘려야 할 신호.
    },
  },
  thresholds: draftThresholds,
  tags: { scenario: SCENARIO_TAG, stage: 'baseline' },
};

export default function () {
  const account = pickAccount(__VU);
  const accessToken = getAccessToken(account);
  if (!accessToken) return;

  const travelId = pickTravelId(__VU, __ITER);

  // 요청 모델 초안(조회 비중이 쓰기보다 훨씬 큼)을 단순하게 근사: 5회 중 1회만 쓰기.
  planReadFlow(accessToken, travelId);
  if (__ITER % 5 === 0) {
    timelineWriteFlow(accessToken, travelId, __VU, __ITER);
  }

  sleep(0.2);
}

export function handleSummary(data) {
  return sharedHandleSummary(data, { stage: 'baseline' });
}
