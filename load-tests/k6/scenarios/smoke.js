import { mapPoints, travelDetail, travelList } from '../flows/travel-read.js';
import { orderChange, timelineCreate } from '../flows/timeline-write.js';
import { makeSummaryHandler } from '../summary.js';

export const options = {
  scenarios: {
    smoke: { executor: 'per-vu-iterations', vus: 2, iterations: 1, maxDuration: '2m' },
  },
};

export default function smoke() {
  travelList();
  travelDetail();
  mapPoints();
  const timelineItemId = timelineCreate();
  if (timelineItemId) orderChange();
}

export const handleSummary = makeSummaryHandler('smoke');
