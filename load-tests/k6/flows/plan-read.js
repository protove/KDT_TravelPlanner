import http from 'k6/http';
import { check, group } from 'k6';
import { BASE_URL } from '../lib/config.js';
import { authHeaders } from '../lib/auth.js';

export function planReadFlow(accessToken, travelId) {
  group('plan_read', function () {
    const listRes = http.get(`${BASE_URL}/api/v1/travels?page=0&size=20`, {
      headers: authHeaders(accessToken),
      tags: { name: 'travels_list' },
    });
    check(listRes, { 'travels list 200': (r) => r.status === 200 });

    const detailRes = http.get(`${BASE_URL}/api/v1/travels/${travelId}`, {
      headers: authHeaders(accessToken),
      tags: { name: 'travel_detail' },
    });
    check(detailRes, { 'travel detail 200': (r) => r.status === 200 });

    const mapRes = http.get(
      `${BASE_URL}/api/v1/travels/${travelId}/map-points?dayNumber=1`,
      {
        headers: authHeaders(accessToken),
        tags: { name: 'travel_map_points' },
      }
    );
    check(mapRes, { 'map points 200 or 404': (r) => r.status === 200 || r.status === 404 });
  });
}