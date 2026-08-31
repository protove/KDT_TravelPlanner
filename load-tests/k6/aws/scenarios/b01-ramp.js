// AWS B-01 Ramp scenario. Diagnostic: finds the maximum stable RPS candidate
// that D-005 will use to set profile.scenarios.baseline.rate. Reuses the
// same request mix ratios as b01-baseline.js / Compose baseline.js
// (requestMix.baseline in the profile), just at increasing rate.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { accessToken } from '../../lib/auth.js';
import { recordCoreOperation } from '../lib/core-metrics.js';
import { b01RampThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import { SCENARIOS, enforceRateLimit, enforceVuLimit, requestMixFor } from '../config.js';

const RAMP = SCENARIOS.ramp;
if (!RAMP) throw new Error('[aws/b01-ramp] profile.scenarios.ramp is missing');
if (!Array.isArray(RAMP.stages) || RAMP.stages.length === 0) {
  throw new Error('[aws/b01-ramp] profile.scenarios.ramp.stages must be a non-empty array');
}

const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || RAMP.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || RAMP.maxVUs));
const START_RATE = enforceRateLimit(Number(__ENV.START_RATE || RAMP.startRate));
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
  if (!Number.isFinite(weight)) throw new Error(`[aws/b01-ramp] requestMix.normal.${key} is missing`);
  cursor += weight;
  return { key, upperBound: cursor };
});
if (Math.round(cursor) !== 100) throw new Error(`[aws/b01-ramp] requestMix.normal must sum to 100, got ${cursor}`);

const stages = RAMP.stages.map((stage) => ({
  target: enforceRateLimit(Number(stage.targetRate)),
  duration: stage.duration,
}));

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    ramp: {
      executor: RAMP.executor || 'ramping-arrival-rate',
      startRate: START_RATE,
      timeUnit: RAMP.timeUnit || '1s',
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      stages,
      exec: 'mix',
      tags: { phase: 'b01-ramp' },
    },
  },
  thresholds: b01RampThresholds,
};

export function mix() {
  const choice = Math.random() * 100;
  const match = BOUNDARIES.find((boundary) => choice < boundary.upperBound);
  FLOWS[match.key]();
}

export const handleSummary = makeAwsSummaryHandler('aws-b01-ramp');
