import { makeSummaryHandler } from '../summary.js';
import { accessToken } from '../lib/auth.js';
import { mapPoints, travelDetail, travelList } from '../flows/travel-read.js';

const RATE = Number(__ENV.RATE || 8);

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s',
      duration: __ENV.DURATION || '16m',
      preAllocatedVUs: Number(__ENV.PREALLOCATED_VUS || 20),
      maxVUs: Number(__ENV.MAX_VUS || 20), exec: 'recoveryMix',
    },
  },
  // Intentional restart errors are evaluated by evaluate-recovery.py by time window.
  thresholds: {},
};

export function recoveryMix() {
  const choice = Math.random() * 100;
  if (choice < 15) accessToken({ forceRefresh: true });
  else if (choice < 55) travelList();
  else if (choice < 80) travelDetail();
  else mapPoints();
}

export default function recoverySteady() {
  recoveryMix();
}
export const handleSummary = makeSummaryHandler('recovery-steady');
