import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';
import { API } from '../lib/config.js';
import { vuCredential } from '../lib/data.js';
import { record } from '../lib/metrics.js';

export const diagnosticReorderItemCount = new Trend('diagnostic_reorder_item_count');
export const diagnosticRequestBodyBytes = new Trend('diagnostic_request_body_bytes');
export const diagnosticSuccessfulRequests = new Counter('diagnostic_successful_requests');
export const diagnosticContractFailures = new Rate('diagnostic_contract_failures');

const states = {};

function state() {
  const vuId = exec.vu.idInTest;
  if (!states[vuId]) {
    const credential = vuCredential();
    states[vuId] = {
      refreshToken: credential.refreshToken,
      fixedIds: (credential.fixedOrderTimelineItemIds || []).slice(),
      growingIds: (credential.growingTimelineItemIds || []).slice(),
      fixedFlip: false,
      nextVisitOrder: (credential.scratchTimelineItemIds || []).length + 1,
      accessToken: null,
    };
  }
  return states[vuId];
}

function bucket(count) {
  if (count <= 3) return '1-3';
  if (count <= 10) return '4-10';
  if (count <= 25) return '11-25';
  if (count <= 50) return '26-50';
  return '51+';
}

function tags(context, operation, extra = {}) {
  return {
    name: context.name || operation,
    flow: 'dependency-diagnostic',
    diagnostic_variant: context.variant,
    diagnostic_phase: context.phase,
    diagnostic_operation: operation,
    ...extra,
  };
}

function refreshToken(context, operation) {
  const current = state();
  const response = http.post(`${API}/auth/token/refresh`, null, {
    headers: { Cookie: `refresh_token=${current.refreshToken}` },
    tags: tags(context, operation),
  });
  record(response, { expect: [200] });
  const rotated = response.cookies?.refresh_token?.[0]?.value;
  const accessToken = response.json('data.accessToken');
  const ok = response.status === 200 && rotated && accessToken;
  diagnosticContractFailures.add(ok ? 0 : 1, tags(context, operation));
  if (ok) {
    current.refreshToken = rotated;
    current.accessToken = accessToken;
    diagnosticSuccessfulRequests.add(1, tags(context, operation));
  }
  check(response, { 'diagnostic refresh 200': (result) => result.status === 200 });
  return current.accessToken;
}

function authHeaders(context, operation) {
  const current = state();
  if (!current.accessToken) refreshToken(context, operation);
  return {
    Authorization: `Bearer ${current.accessToken || ''}`,
    'Content-Type': 'application/json',
  };
}

function request(context, operation, method, path, body = null, expected = [200, 201, 204]) {
  const payload = body === null ? null : JSON.stringify(body);
  if (payload !== null) diagnosticRequestBodyBytes.add(payload.length, tags(context, operation));
  let response = http.request(method, `${API}${path}`, payload, {
    headers: authHeaders(context, operation),
    tags: tags(context, operation),
  });
  if (response.status === 401) {
    state().accessToken = null;
    refreshToken(context, operation);
    response = http.request(method, `${API}${path}`, payload, {
      headers: authHeaders(context, operation),
      tags: tags(context, operation),
    });
  }
  const ok = expected.includes(response.status);
  record(response, { expect: expected });
  diagnosticContractFailures.add(ok ? 0 : 1, tags(context, operation));
  if (ok) diagnosticSuccessfulRequests.add(1, tags(context, operation));
  check(response, { [`${operation} contract`]: (result) => expected.includes(result.status) });
  return response;
}

export function chooseDiagnosticOperation(mix) {
  const draw = Math.random() * 100;
  let cursor = 0;
  for (const [operation, weight] of Object.entries(mix)) {
    cursor += Number(weight);
    if (draw < cursor) return operation;
  }
  return Object.keys(mix).at(-1);
}

function travelList(context) {
  return request(context, 'travelList', 'GET', '/travels');
}

function travelDetail(context) {
  return request(context, 'travelDetail', 'GET', `/travels/${vuCredential().readTravelId}`);
}

function mapPoints(context) {
  return request(context, 'mapPoints', 'GET', `/travels/${vuCredential().readTravelId}/map-points?dayNumber=1`);
}

function createTimelineItem(context, travelId, operation) {
  const current = state();
  const response = request(context, operation, 'POST', `/travels/${travelId}/timeline-items`, {
    dayNumber: 1,
    visitDate: vuCredential().visitDate,
    category: '관광지',
    name: `${operation}-${current.nextVisitOrder}`,
    visitOrder: current.nextVisitOrder,
  });
  if (response.status === 200 || response.status === 201) {
    const itemId = response.json('data.timelineItemId');
    current.nextVisitOrder += 1;
    if (operation === 'timelineCreate') current.growingIds.push(itemId);
  }
  return response;
}

function reorder(context, itemIds, operation, travelId) {
  const itemCount = itemIds.length;
  const items = itemIds.slice().reverse().map((itemId, index) => ({ itemId, visitOrder: index + 1 }));
  diagnosticReorderItemCount.add(itemCount, {
    diagnostic_variant: context.variant,
    diagnostic_phase: context.phase,
    diagnostic_operation: operation,
    diagnostic_item_count_bucket: bucket(itemCount),
  });
  return request(context, operation, 'PATCH', `/travels/${travelId}/timeline-items/order`, {
    dayNumber: 1,
    items,
  });
}

function fixedReorder(context) {
  const current = state();
  current.fixedFlip = !current.fixedFlip;
  const ids = current.fixedFlip ? current.fixedIds : current.fixedIds.slice().reverse();
  return reorder(context, ids, 'alternatingThreeItemReorder', vuCredential().fixedOrderTravelId);
}

function growingReorder(context) {
  return reorder(context, state().growingIds, 'reverseAllItemsReorder', vuCredential().growingTravelId);
}

export function runDiagnosticOperation(operation, context) {
  switch (operation) {
    case 'refresh':
      state().accessToken = null;
      return refreshToken(context, operation);
    case 'travelList': return travelList(context);
    case 'travelDetail': return travelDetail(context);
    case 'mapPoints': return mapPoints(context);
    case 'timelineCreateOnScratchTravel': return createTimelineItem(context, vuCredential().scratchTravelId, operation);
    case 'alternatingThreeItemReorder': return fixedReorder(context);
    case 'timelineCreate': return createTimelineItem(context, vuCredential().growingTravelId, operation);
    case 'reverseAllItemsReorder': return growingReorder(context);
    default: throw new Error(`unsupported diagnostic operation: ${operation}`);
  }
}
