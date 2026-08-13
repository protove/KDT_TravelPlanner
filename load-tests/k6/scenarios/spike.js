import { mapPoints, travelDetail, travelList } from '../flows/travel-read.js';
import { accessToken } from '../lib/auth.js';
import { makeSummaryHandler } from '../summary.js';

const RATE = Number(__ENV.RATE || 8);
const PEAK_RATE = Number(__ENV.SPIKE_PEAK_RATE || RATE * 3);
const HOLD = __ENV.SPIKE_HOLD || '1m';

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    spike: {
      executor: 'ramping-arrival-rate',
      startRate: RATE,
      timeUnit: '1s',
      preAllocatedVUs: Number(__ENV.PREALLOCATED_VUS || 20),
      maxVUs: Number(__ENV.MAX_VUS || 80),
      stages: [
        { target: RATE, duration: '30s' },
        { target: PEAK_RATE, duration: '30s' },
        { target: PEAK_RATE, duration: HOLD },
        { target: RATE, duration: '30s' },
        { target: 0, duration: '30s' },
      ],
      exec: 'spikeMix',
    },
  },
  // Spike is diagnostic: the Gate records overload and runner limits separately.
  thresholds: {},
};

export function spikeMix() {
  const choice = Math.random() * 100;
  if (choice < 15) accessToken({ forceRefresh: true });
  else if (choice < 55) travelList();
  else if (choice < 80) travelDetail();
  else mapPoints();
}

export default function spike() {
  spikeMix();
}

export const handleSummary = makeSummaryHandler('spike');
