// Separate post-freeze Capacity/Scale Stress scenario.
// It deliberately does not alter the original Scale-step scenario: the
// normal rate/SLO is supplied by the operator after the six Baselines, and
// this file only materializes the preregistered 1x/2x/4x/8x stages.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { accessToken } from '../../lib/auth.js';
import { recordCoreOperation } from '../lib/core-metrics.js';
import { b01SpikeThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import { LIMITS, SCENARIOS, enforceRateLimit, enforceVuLimit, requestMixFor } from '../config.js';

const STRESS = SCENARIOS['capacity-stress'];
if (!STRESS) throw new Error('[aws/capacity-stress] profile.scenarios.capacity-stress is missing');

const RATE = Number(__ENV.CONFIRMED_RATE || __ENV.RATE || STRESS.startRate);
if (!Number.isFinite(RATE) || RATE <= 0) {
  throw new Error('[aws/capacity-stress] CONFIRMED_RATE must be a positive frozen normal rate');
}
const MULTIPLIERS = STRESS.stageMultipliers || [];
const DURATIONS = STRESS.stageDurations || [];
if (MULTIPLIERS.length !== 4 || JSON.stringify(MULTIPLIERS) !== JSON.stringify([1, 2, 4, 8])) {
  throw new Error('[aws/capacity-stress] stageMultipliers must be [1, 2, 4, 8]');
}
if (DURATIONS.length !== MULTIPLIERS.length) {
  throw new Error('[aws/capacity-stress] stageDurations must match stageMultipliers');
}
const STAGE_RATES = MULTIPLIERS.map((multiplier) => enforceRateLimit(RATE * Number(multiplier)));
if (STAGE_RATES.some((stageRate) => stageRate > LIMITS.maxRate)) {
  throw new Error(`[aws/capacity-stress] stage rate exceeds profile limits.maxRate ${LIMITS.maxRate}`);
}

const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || STRESS.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || STRESS.maxVUs));
if (MAX_VUS < 300) throw new Error('[aws/capacity-stress] maxVUs must be at least 300');
const MIX = requestMixFor('normal');
const FLOWS = {
  refresh: () => accessToken({ forceRefresh: true }),
  travelList: () => recordCoreOperation(travelList),
  travelDetail: () => recordCoreOperation(travelDetail),
  mapPoints: () => recordCoreOperation(mapPoints),
  timelineCreate: () => recordCoreOperation(timelineCreate),
  orderChange: () => recordCoreOperation(orderChange),
};
const ORDER = Object.keys(FLOWS);
let cursor = 0;
const BOUNDARIES = ORDER.map((key) => {
  const weight = Number(MIX[key]);
  if (!Number.isFinite(weight)) throw new Error(`[aws/capacity-stress] requestMix.normal.${key} is missing`);
  cursor += weight;
  return { key, upperBound: cursor };
});
if (Math.round(cursor) !== 100) throw new Error(`[aws/capacity-stress] requestMix.normal must sum to 100, got ${cursor}`);

const stages = STAGE_RATES.map((target, index) => ({ target, duration: DURATIONS[index] }));

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    capacityStress: {
      executor: STRESS.executor || 'ramping-arrival-rate',
      startRate: STAGE_RATES[0],
      timeUnit: STRESS.timeUnit || '1s',
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      stages,
      exec: 'mix',
      tags: { phase: 'capacity-stress' },
    },
  },
  // The run is diagnostic. The external evaluator applies the frozen SLO to
  // consecutive windows and stops/labels the campaign; k6 must still record
  // all samples up to that terminal point.
  thresholds: b01SpikeThresholds,
};

export function mix() {
  const choice = Math.random() * 100;
  const match = BOUNDARIES.find((boundary) => choice < boundary.upperBound);
  FLOWS[match.key]();
}

export const handleSummary = makeAwsSummaryHandler('aws-comparison-capacity-stress');
