// AWS smoke scenario. Reuses the existing Compose flows unchanged; only the
// target (via BASE_URL, validated in ../config.js) and the metrics wrapper
// (../lib/core-metrics.js) differ from the Compose smoke.js.
import { mapPoints, travelDetail, travelList } from '../../flows/travel-read.js';
import { orderChange, timelineCreate } from '../../flows/timeline-write.js';
import { recordCoreOperation } from '../lib/core-metrics.js';
import { smokeThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';

export const options = {
  scenarios: {
    smoke: { executor: 'per-vu-iterations', vus: 2, iterations: 1, maxDuration: '2m' },
  },
  thresholds: smokeThresholds,
};

export default function smoke() {
  recordCoreOperation(travelList);
  recordCoreOperation(travelDetail);
  recordCoreOperation(mapPoints);
  const timelineItemId = recordCoreOperation(timelineCreate);
  if (timelineItemId) recordCoreOperation(orderChange);
}

export const handleSummary = makeAwsSummaryHandler('aws-smoke');
