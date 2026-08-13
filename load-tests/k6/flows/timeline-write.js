import http from 'k6/http';
import { check, group } from 'k6';
import { BASE_URL } from '../lib/config.js';
import { authHeaders } from '../lib/auth.js';

export function timelineWriteFlow(accessToken, travelId, vuId, iter) {
  group('timeline_write', function () {
    const today = new Date().toISOString().slice(0, 10);
    const payload = JSON.stringify({
      dayNumber: 1,
      visitDate: today,
      cityId: 10,
      category: '관광지',
      foodSubcategory: null,
      name: `k6 load test item ${vuId}-${iter}`,
      googlePlaceId: null,
      visitOrder: 1,
      memo: null,
    });

    const createRes = http.post(
      `${BASE_URL}/api/v1/travels/${travelId}/timeline-items`,
      payload,
      {
        headers: authHeaders(accessToken),
        tags: { name: 'timeline_item_create' },
      }
    );
    const created = check(createRes, {
      'timeline create 200/201': (r) => r.status === 200 || r.status === 201,
    });
    if (!created) return;

    const itemId = JSON.parse(createRes.body).data.timelineItemId;

    const updateRes = http.patch(
      `${BASE_URL}/api/v1/travels/${travelId}/timeline-items/${itemId}`,
      JSON.stringify({ memo: 'k6 updated' }),
      {
        headers: authHeaders(accessToken),
        tags: { name: 'timeline_item_update' },
      }
    );
    check(updateRes, { 'timeline update 200': (r) => r.status === 200 });

    const deleteRes = http.del(
      `${BASE_URL}/api/v1/travels/${travelId}/timeline-items/${itemId}`,
      null,
      {
        headers: authHeaders(accessToken),
        tags: { name: 'timeline_item_delete' },
      }
    );
    check(deleteRes, { 'timeline delete 200/204': (r) => r.status === 200 || r.status === 204 });
  });
}
