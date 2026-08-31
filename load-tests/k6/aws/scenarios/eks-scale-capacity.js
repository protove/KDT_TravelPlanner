// EKS monolith breakpoint scenario.
//
// This is intentionally a bounded diagnostic curve. It keeps increasing the
// arrival rate until an explicit SLO/platform terminal condition is observed,
// while preserving the 2/2/4 node-group contract and never calling Kubernetes
// or AWS control-plane APIs from the load runner.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { accessToken } from '../../lib/auth.js';
import { recordCoreOperation } from '../lib/core-metrics.js';
import { b01SpikeThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import { LIMITS, SCENARIOS, enforceRateLimit, enforceVuLimit, requestMixFor } from '../config.js';

const STRESS = SCENARIOS['capacity-stress'];
if (!STRESS) throw new Error('[aws/eks-scale-capacity] profile.scenarios.capacity-stress is missing');
const RATE = Number(__ENV.CONFIRMED_RATE || __ENV.RATE || STRESS.startRate);
if (!Number.isFinite(RATE) || RATE <= 0) {
  throw new Error('[aws/eks-scale-capacity] CONFIRMED_RATE must be a positive frozen normal rate');
}

const MULTIPLIERS = STRESS.stageMultipliers || [];
const DURATIONS = STRESS.stageDurations || [];
if (MULTIPLIERS.length < 5 || MULTIPLIERS[0] !== 1) {
  throw new Error('[aws/eks-scale-capacity] at least five stages starting at 1x are required');
}
for (let index = 1; index < MULTIPLIERS.length; index += 1) {
  if (MULTIPLIERS[index] !== MULTIPLIERS[index - 1] * 2) {
    throw new Error('[aws/eks-scale-capacity] stageMultipliers must double monotonically');
  }
}
if (DURATIONS.length !== MULTIPLIERS.length) {
  throw new Error('[aws/eks-scale-capacity] stageDurations must match stageMultipliers');
}
const STAGE_RATES = MULTIPLIERS.map((multiplier) => enforceRateLimit(RATE * Number(multiplier)));
const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || STRESS.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || STRESS.maxVUs));
const MIX = requestMixFor('normal');
const FLOWS = {
  refresh: () => accessToken({ forceRefresh: true }),
  travelList: () => recordCoreOperation(travelList),
  travelDetail: () => recordCoreOperation(travelDetail),
  mapPoints: () => recordCoreOperation(mapPoints),
  timelineCreate: () => recordCoreOperation(timelineCreate),
  orderChange: () => recordCoreOperation(orderChange),
};
let cursor = 0;
const BOUNDARIES = Object.keys(FLOWS).map((key) => {
  const weight = Number(MIX[key]);
  if (!Number.isFinite(weight)) throw new Error(`[aws/eks-scale-capacity] requestMix.normal.${key} is missing`);
  cursor += weight;
  return { key, upperBound: cursor };
});
if (Math.round(cursor) !== 100) throw new Error(`[aws/eks-scale-capacity] requestMix.normal must sum to 100, got ${cursor}`);

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    eksScaleCapacity: {
      executor: STRESS.executor || 'ramping-arrival-rate',
      startRate: STAGE_RATES[0],
      timeUnit: STRESS.timeUnit || '1s',
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      stages: STAGE_RATES.map((target, index) => ({ target, duration: DURATIONS[index] })),
      exec: 'mix',
      tags: { phase: 'eks-monolith-breakpoint', platform: 'eks' },
    },
  },
  // Thresholds remain diagnostic. The coordinator/evaluator owns complete
  // 60-second SLO windows and terminal classification.
  thresholds: b01SpikeThresholds,
};

export function mix() {
  const choice = Math.random() * 100;
  const match = BOUNDARIES.find((boundary) => choice < boundary.upperBound);
  FLOWS[match.key]();
}

export const handleSummary = makeAwsSummaryHandler('aws-eks-monolith-breakpoint');
