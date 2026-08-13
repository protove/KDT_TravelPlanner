import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { API } from '../lib/config.js';
import { withAuthRetry } from '../lib/auth.js';
import {
  nextVisitOrder,
  registerTimelineItem,
  timelineItemIds,
  travelId,
  visitDate,
} from '../lib/data.js';
import { record } from '../lib/metrics.js';

export function timelineCreate() {
  const response = withAuthRetry((headers) => http.post(
    `${API}/travels/${travelId()}/timeline-items`,
    JSON.stringify({
      dayNumber: 1,
      visitDate: visitDate(),
      category: '관광지',
      name: `load-${exec.vu.idInTest}-${exec.scenario.iterationInTest}`,
      visitOrder: nextVisitOrder(),
    }),
    { headers, tags: { name: 'POST /travels/{travelId}/timeline-items', flow: 'timeline-write' } },
  ));
  record(response, { expect: [200, 201] });
  check(response, { 'timeline create 2xx': (result) => result.status === 200 || result.status === 201 });
  if (response.status >= 200 && response.status < 300) {
    const id = response.json('data.timelineItemId');
    registerTimelineItem(id);
    return id;
  }
  return null;
}

export function orderChange() {
  const itemIds = timelineItemIds();
  if (itemIds.length < 2) return;
  const response = withAuthRetry((headers) => http.patch(
    `${API}/travels/${travelId()}/timeline-items/order`,
    JSON.stringify({
      dayNumber: 1,
      items: itemIds.slice().reverse().map((itemId, index) => ({
        itemId,
        visitOrder: index + 1,
      })),
    }),
    { headers, tags: { name: 'PATCH /travels/{travelId}/timeline-items/order', flow: 'timeline-write' } },
  ));
  record(response, { expect: [200, 204], allowDomain4xx: false });
  check(response, { 'timeline order 2xx': (result) => result.status === 200 || result.status === 204 });
}
