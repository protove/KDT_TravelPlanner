import { mapPoints, travelDetail, travelList } from '../flows/travel-read.js';
import { orderChange, timelineCreate } from '../flows/timeline-write.js';
import { accessToken } from '../lib/auth.js';
import { rehearsalThresholds } from '../config/thresholds.js';
import { makeSummaryHandler } from '../summary.js';

const RATE = Number(__ENV.RATE || 8);
const DURATION = __ENV.DURATION || '10m';
const WARMUP = __ENV.WARMUP || '3m';

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
  return `${Math.ceil(durationSeconds(WARMUP) + durationSeconds(DURATION))}s`;
}

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    baseline: {
      // Keep one VU lifecycle across warmup and normal load so rotating refresh
      // tokens are not reset at a scenario boundary.
      executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s', duration: totalDuration(),
      preAllocatedVUs: Number(__ENV.PREALLOCATED_VUS || 20),
      maxVUs: Number(__ENV.MAX_VUS || 20), exec: 'mix', tags: { phase: 'baseline' },
    },
  },
  thresholds: rehearsalThresholds,
};

export function mix() {
  const choice = Math.random() * 100;
  if (choice < 12) accessToken({ forceRefresh: true });
  else if (choice < 34) travelList();
  else if (choice < 54) travelDetail();
  else if (choice < 72) mapPoints();
  else if (choice < 90) timelineCreate();
  else orderChange();
}

export const handleSummary = makeSummaryHandler('baseline');
