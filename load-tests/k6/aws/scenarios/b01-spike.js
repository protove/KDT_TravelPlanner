// AWS B-01 Spike scenario. Diagnostic, same as Compose spike.js: intentional
// peak overload during the hold stage is expected and not held to the SLO
// (see b01SpikeThresholds). Peaks off the same D-005 baseline rate, so it
// cannot run before requireScenarioRate('baseline') has a value.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { accessToken } from '../../lib/auth.js';
import { recordCoreOperation } from '../lib/core-metrics.js';
import { b01SpikeThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import {
  LIMITS, SCENARIOS, REQUEST_MIX, enforceRateLimit, enforceVuLimit, requireScenarioRate,
} from '../config.js';

const SPIKE = SCENARIOS.spike;
if (!SPIKE) throw new Error('[aws/b01-spike] profile.scenarios.spike is missing');

const RATE = requireScenarioRate('baseline');
const PEAK_MULTIPLIER = Number(__ENV.SPIKE_PEAK_MULTIPLIER || SPIKE.peakRateMultiplier);
if (!Number.isFinite(PEAK_MULTIPLIER) || PEAK_MULTIPLIER <= 1) {
  throw new Error('[aws/b01-spike] peak multiplier must be greater than 1');
}
const REQUESTED_PEAK_RATE = RATE * PEAK_MULTIPLIER;
if (!(RATE < REQUESTED_PEAK_RATE)) {
  throw new Error('[aws/b01-spike] peak rate must be greater than baseline rate');
}
if (REQUESTED_PEAK_RATE > LIMITS.maxRate) {
  throw new Error(`[aws/b01-spike] peak rate ${REQUESTED_PEAK_RATE} exceeds profile limits.maxRate ${LIMITS.maxRate}`);
}
const PEAK_RATE = enforceRateLimit(REQUESTED_PEAK_RATE);
const HOLD = __ENV.SPIKE_HOLD || SPIKE.hold || '1m';
const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || SPIKE.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || SPIKE.maxVUs));

const MIX = REQUEST_MIX.spike;
if (!MIX) throw new Error('[aws/b01-spike] profile.requestMix.spike is missing');

const FLOWS = {
  refresh: () => accessToken({ forceRefresh: true }),
  travelList: () => recordCoreOperation(travelList),
  travelDetail: () => recordCoreOperation(travelDetail),
  mapPoints: () => recordCoreOperation(mapPoints),
  timelineCreate: () => recordCoreOperation(timelineCreate),
  orderChange: () => recordCoreOperation(orderChange),
};

const order = ['refresh', 'travelList', 'travelDetail', 'mapPoints', 'timelineCreate', 'orderChange'];
let cursor = 0;
const boundaries = order.map((key) => {
  const weight = MIX[key];
  if (!Number.isFinite(weight)) throw new Error(`[aws/b01-spike] requestMix.spike.${key} is missing`);
  cursor += weight;
  return { key, upperBound: cursor };
});
if (Math.round(cursor) !== 100) {
  throw new Error(`[aws/b01-spike] requestMix.spike weights must sum to 100, got ${cursor}`);
}

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    spike: {
      executor: SPIKE.executor || 'ramping-arrival-rate',
      startRate: RATE,
      timeUnit: '1s',
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      stages: [
        { target: RATE, duration: '30s' },
        { target: PEAK_RATE, duration: '30s' },
        { target: PEAK_RATE, duration: HOLD },
        { target: RATE, duration: '30s' },
        { target: 0, duration: '30s' },
      ],
      exec: 'spikeMix',
      tags: { phase: 'b01-spike' },
    },
  },
  thresholds: b01SpikeThresholds,
};

export function spikeMix() {
  const choice = Math.random() * 100;
  const match = boundaries.find((boundary) => choice < boundary.upperBound);
  FLOWS[match.key]();
}

export default function spike() {
  spikeMix();
}

export const handleSummary = makeAwsSummaryHandler('aws-b01-spike');
