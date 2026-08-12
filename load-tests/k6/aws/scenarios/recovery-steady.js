// AWS recovery steady workload. It keeps one VU lifecycle across warm-up and
// the intervention/recovery window so auth refresh state is not reset. Any
// intervention is performed by a scenario adapter; this script only emits
// the read/write Core API operation counters used by the evaluator.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { accessToken } from '../../lib/auth.js';
import { recordCoreOperation } from '../lib/recovery-core-metrics.js';
import { makeRecoverySummaryHandler } from '../recovery-summary.js';
import {
  RATE, RECOVERY_OPTIONS, REQUEST_MIX, ENVIRONMENT, REGION, REQUEST_MIX_VERSION,
} from '../recovery-config.js';

function durationSeconds(value) {
  const pattern = /(\d+(?:\.\d+)?)(ms|s|m|h)/g;
  let total = 0;
  let consumed = 0;
  let match;
  while ((match = pattern.exec(value)) !== null) {
    if (match.index !== consumed) throw new Error(`invalid duration: ${value}`);
    const amount = Number(match[1]);
    const multiplier = { ms: 0.001, s: 1, m: 60, h: 3600 }[match[2]];
    total += amount * multiplier;
    consumed = pattern.lastIndex;
  }
  if (consumed !== value.length || total <= 0) throw new Error(`invalid duration: ${value}`);
  return total;
}

function totalDuration() {
  if (__ENV.TOTAL_DURATION) return __ENV.TOTAL_DURATION;
  return `${Math.ceil(durationSeconds(RECOVERY_OPTIONS.warmup) + durationSeconds(RECOVERY_OPTIONS.duration))}s`;
}

const order = ['refresh', 'travelList', 'travelDetail', 'mapPoints', 'timelineCreate', 'orderChange'];
let cursor = 0;
const boundaries = order.map((key) => {
  const weight = Number(REQUEST_MIX[key]);
  if (!Number.isFinite(weight) || weight < 0) throw new Error(`invalid requestMix.steady.${key}`);
  cursor += weight;
  return { key, upperBound: cursor };
});
if (Math.round(cursor) !== 100) throw new Error(`requestMix.steady weights must sum to 100, got ${cursor}`);

const FLOWS = {
  refresh: () => accessToken({ forceRefresh: true }),
  travelList: () => recordCoreOperation(travelList),
  travelDetail: () => recordCoreOperation(travelDetail),
  mapPoints: () => recordCoreOperation(mapPoints),
  timelineCreate: () => recordCoreOperation(timelineCreate),
  orderChange: () => recordCoreOperation(orderChange),
};

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    steady: {
      executor: RECOVERY_OPTIONS.executor,
      rate: RATE,
      timeUnit: RECOVERY_OPTIONS.timeUnit,
      duration: totalDuration(),
      preAllocatedVUs: RECOVERY_OPTIONS.preAllocatedVUs,
      maxVUs: RECOVERY_OPTIONS.maxVUs,
      exec: 'recoveryMix',
      tags: { phase: 'aws-recovery-steady', environment: ENVIRONMENT, region: REGION },
    },
  },
  thresholds: {},
};

export function recoveryMix() {
  const choice = Math.random() * 100;
  const match = boundaries.find((boundary) => choice < boundary.upperBound);
  FLOWS[match.key]();
}

export default function recoverySteady() {
  recoveryMix();
}

export const handleSummary = makeRecoverySummaryHandler('aws-recovery-steady');
