import exec from 'k6/execution';
import { makeSummaryHandler } from '../summary.js';
import {
  chooseDiagnosticOperation,
  runDiagnosticOperation,
} from '../flows/dependency-diagnostic.js';

const profile = JSON.parse(open(__ENV.PROFILE_FILE || '/profile/diagnostic-profile.json'));
const variantId = __ENV.DIAGNOSTIC_VARIANT || 'growing-cardinality-mixed';
const variant = profile.variants.find((candidate) => candidate.id === variantId);
if (!variant) throw new Error(`unknown diagnostic variant: ${variantId}`);

function durationSeconds(value) {
  const match = /^(\d+)(ms|s|m|h)$/.exec(value);
  if (!match) throw new Error(`invalid duration: ${value}`);
  const multiplier = { ms: 0.001, s: 1, m: 60, h: 3600 }[match[2]];
  return Number(match[1]) * multiplier;
}

const warmupSeconds = durationSeconds(profile.profile.warmup);
const measuredSeconds = durationSeconds(profile.profile.measuredDuration);
const totalSeconds = warmupSeconds + measuredSeconds;

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    diagnostic: {
      executor: 'constant-arrival-rate',
      rate: Number(profile.profile.ratePerSecond),
      timeUnit: '1s',
      duration: `${totalSeconds}s`,
      preAllocatedVUs: Number(profile.profile.preallocatedVUs),
      maxVUs: Number(profile.profile.maxVUs),
      exec: 'diagnostic',
      tags: { diagnostic_variant: variantId },
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    unexpected_errors: ['rate<0.01'],
    contract_fail: ['rate<0.01'],
  },
};

export function diagnostic() {
  const phase = exec.scenario.progressInTest < warmupSeconds / totalSeconds ? 'warmup' : 'measured';
  const operation = chooseDiagnosticOperation(variant.requestMix);
  runDiagnosticOperation(operation, { variant: variantId, phase });
}

export const handleSummary = makeSummaryHandler(`dependency-diagnostic:${variantId}`);
