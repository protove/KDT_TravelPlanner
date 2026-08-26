// Comparison soak: write-inclusive normal traffic for a sustained window.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { accessToken } from '../../lib/auth.js';
import { recordCoreOperation } from '../lib/core-metrics.js';
import { b01BaselineThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import { SCENARIOS, enforceVuLimit, requestMixFor, requireScenarioRate } from '../config.js';

const SOAK = SCENARIOS.soak;
if (!SOAK) throw new Error('[aws/soak] profile.scenarios.soak is missing');
const RATE = requireScenarioRate('soak');
const WARMUP = __ENV.WARMUP || SOAK.warmup || '3m';
const DURATION = __ENV.DURATION || SOAK.duration || '30m';
const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || SOAK.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || SOAK.maxVUs));
const MIX = requestMixFor('soak');
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
  if (!Number.isFinite(weight)) throw new Error(`[aws/soak] requestMix.soak.${key} is missing`);
  cursor += weight;
  BOUNDARIES.push({ key, upperBound: cursor });
}
if (Math.round(cursor) !== 100) throw new Error(`[aws/soak] requestMix.soak must sum to 100, got ${cursor}`);

function durationSeconds(value) {
  const match = /^(\d+)(ms|s|m|h)$/.exec(value);
  if (!match) throw new Error(`[aws/soak] invalid duration: ${value}`);
  return Number(match[1]) * ({ ms: 0.001, s: 1, m: 60, h: 3600 }[match[2]]);
}

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    soak: {
      executor: SOAK.executor || 'constant-arrival-rate',
      rate: RATE,
      timeUnit: SOAK.timeUnit || '1s',
      duration: `${Math.ceil(durationSeconds(WARMUP) + durationSeconds(DURATION))}s`,
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      exec: 'mix',
      tags: { phase: 'comparison-soak' },
    },
  },
  thresholds: b01BaselineThresholds,
};

export function mix() {
  const choice = Math.random() * 100;
  const match = BOUNDARIES.find((boundary) => choice < boundary.upperBound);
  FLOWS[match.key]();
}

export const handleSummary = makeAwsSummaryHandler('aws-comparison-soak');
