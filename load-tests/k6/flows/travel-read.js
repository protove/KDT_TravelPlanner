import http from 'k6/http';
import { check } from 'k6';
import { API } from '../lib/config.js';
import { withAuthRetry } from '../lib/auth.js';
import { travelId } from '../lib/data.js';
import { record } from '../lib/metrics.js';

export function travelList() {
  const response = withAuthRetry((headers) => http.get(`${API}/travels`, {
    headers,
    tags: { name: 'GET /travels', flow: 'travel-read' },
  }));
  record(response);
  check(response, { 'travel list 200': (result) => result.status === 200 });
}

export function travelDetail() {
  const response = withAuthRetry((headers) => http.get(`${API}/travels/${travelId()}`, {
    headers,
    tags: { name: 'GET /travels/{travelId}', flow: 'travel-read' },
  }));
  record(response);
  check(response, { 'travel detail 200': (result) => result.status === 200 });
}

export function mapPoints() {
  const response = withAuthRetry((headers) => http.get(
    `${API}/travels/${travelId()}/map-points?dayNumber=1`,
    { headers, tags: { name: 'GET /travels/{travelId}/map-points', flow: 'map-read' } },
  ));
  record(response);
  check(response, { 'map points 200': (result) => result.status === 200 });
}
