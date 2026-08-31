// AWS B-01 Baseline scenario. Validates a candidate arrival-rate for 10
// minutes (warmup excluded from measurement per
// contracts/SLO_AND_METRIC_CONTRACT.md). D-005 requires 3 independent runs
// of this scenario before an arrival-rate can be frozen; running it 3 times
// with distinct Run IDs is an orchestration concern (Plan 03), not something
// this script loops internally.
import { runMixedCurrentOperation } from '../flows/current-feature-operations.js';
import { b01BaselineThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import { SCENARIOS, enforceVuLimit, requestMixFor, requireScenarioRate } from '../config.js';

const BASELINE = SCENARIOS.baseline;
if (!BASELINE) throw new Error('[aws/b01-baseline] profile.scenarios.baseline is missing');

const RATE = requireScenarioRate('baseline');
const WARMUP = __ENV.WARMUP || BASELINE.warmup || '3m';
const DURATION = __ENV.DURATION || BASELINE.duration || '10m';
const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || BASELINE.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || BASELINE.maxVUs));
const MIX = requestMixFor('baseline');

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
      // One VU lifecycle across warmup and normal load, same as Compose
      // baseline.js, so rotating refresh tokens are not reset mid-run.
      executor: BASELINE.executor || 'constant-arrival-rate',
      rate: RATE,
      timeUnit: BASELINE.timeUnit || '1s',
      duration: totalDuration(),
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      exec: 'mix',
      tags: { phase: 'b01-baseline' },
    },
  },
  thresholds: b01BaselineThresholds,
};

export function mix() {
  runMixedCurrentOperation(MIX);
}

export const handleSummary = makeAwsSummaryHandler('aws-b01-baseline');
