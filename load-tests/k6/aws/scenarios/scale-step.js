// Comparison scale-step: fixed host capacity, stepped arrival rates.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { accessToken } from '../../lib/auth.js';
import { recordCoreOperation } from '../lib/core-metrics.js';
import { b01RampThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import { SCENARIOS, enforceRateLimit, enforceVuLimit, requestMixFor, requireScenarioRate } from '../config.js';

const SCALE = SCENARIOS['scale-step'];
if (!SCALE) throw new Error('[aws/scale-step] profile.scenarios.scale-step is missing');
const START_RATE = requireScenarioRate('baseline');
const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || SCALE.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || SCALE.maxVUs));
const MIX = requestMixFor('normal');
const FLOWS = {
  refresh: () => accessToken({ forceRefresh: true }),
  travelList: () => recordCoreOperation(travelList),
  travelDetail: () => recordCoreOperation(travelDetail),
  mapPoints: () => recordCoreOperation(mapPoints),
  timelineCreate: () => recordCoreOperation(timelineCreate),
  orderChange: () => recordCoreOperation(orderChange),
};
const BOUNDARIES = [];
let cursor = 0;
for (const key of Object.keys(FLOWS)) {
  const weight = Number(MIX[key]);
  if (!Number.isFinite(weight)) throw new Error(`[aws/scale-step] requestMix.normal.${key} is missing`);
  cursor += weight;
  BOUNDARIES.push({ key, upperBound: cursor });
}
if (Math.round(cursor) !== 100) throw new Error(`[aws/scale-step] requestMix.normal must sum to 100, got ${cursor}`);
const stages = (SCALE.stages || []).map((stage) => ({
  target: enforceRateLimit(Number(stage.targetRate)), duration: stage.duration,
}));

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    scaleStep: {
      executor: SCALE.executor || 'ramping-arrival-rate',
      startRate: enforceRateLimit(Number(__ENV.START_RATE || SCALE.startRate || START_RATE)),
      timeUnit: SCALE.timeUnit || '1s',
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      stages,
      exec: 'mix',
      tags: { phase: 'comparison-scale-step' },
    },
  },
  thresholds: b01RampThresholds,
};

export function mix() {
  const choice = Math.random() * 100;
  const match = BOUNDARIES.find((boundary) => choice < boundary.upperBound);
  FLOWS[match.key]();
}

export const handleSummary = makeAwsSummaryHandler('aws-comparison-scale-step');
