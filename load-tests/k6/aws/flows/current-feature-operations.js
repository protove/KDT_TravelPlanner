// SCRUM-78 AWS current-feature workload.
//
// Each invocation below is exactly one measured Backend API operation.  The
// Google Places/Routes calls made by the Backend are intentionally subrequests
// and are observed through the private Runner mock; they never change the
// target-RPS meaning (operation selections per second).
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { API } from '../../lib/config.js';
import { accessToken, withAuthRetry } from '../../lib/auth.js';
import {
  commentId,
  commentSequence,
  fixtureMarker,
  nextVisitOrder,
  placeIds,
  postId,
  postVersion,
  registerComment,
  registerPlaceIds,
  registerPost,
  setPostVersion,
  setTravelVersion,
  timelineItemIds,
  travelId,
  travelVersion,
} from '../../lib/data.js';
import { record } from '../../lib/metrics.js';
import { recordCoreOperation } from '../lib/core-metrics.js';

export const CURRENT_FEATURE_OPERATIONS = [
  { id: 'refresh', weight: 5, family: 'auth-control', service: 'identity', domain: 'identity', subdomain: 'identity-auth', method: 'POST', route: '/api/v1/auth/token/refresh', coreSlo: false },
  { id: 'profileRead', weight: 3, family: 'profile', service: 'identity', domain: 'identity', subdomain: 'identity-profile', method: 'GET', route: '/api/v1/users/me/profile', coreSlo: true },
  { id: 'travelList', weight: 8, family: 'travel-read', service: 'travel', domain: 'travel', subdomain: 'travel-core', method: 'GET', route: '/api/v1/travels', coreSlo: true },
  { id: 'travelDetail', weight: 8, family: 'travel-read', service: 'travel', domain: 'travel', subdomain: 'travel-core', method: 'GET', route: '/api/v1/travels/{travelId}', coreSlo: true },
  { id: 'travelUpdate', weight: 4, family: 'travel-write', service: 'travel', domain: 'travel', subdomain: 'travel-core', method: 'PATCH', route: '/api/v1/travels/{travelId}', coreSlo: true },
  { id: 'countryList', weight: 1, family: 'location-reference', service: 'travel', domain: 'location', subdomain: 'travel-location', method: 'GET', route: '/api/v1/countries', coreSlo: true },
  { id: 'cityList', weight: 1, family: 'location-reference', service: 'travel', domain: 'location', subdomain: 'travel-location', method: 'GET', route: '/api/v1/countries/{countryId}/cities', coreSlo: true },
  { id: 'placeSearch', weight: 4, family: 'places-mock', service: 'maps', domain: 'places', subdomain: 'maps-places', method: 'GET', route: '/api/v1/places/search', coreSlo: true },
  { id: 'nearbySearch', weight: 2, family: 'places-mock', service: 'maps', domain: 'places', subdomain: 'maps-places', method: 'GET', route: '/api/v1/places/nearby', coreSlo: true },
  { id: 'mapPoints', weight: 4, family: 'map-cache', service: 'maps', domain: 'maps', subdomain: 'maps-cache-orchestration', method: 'GET', route: '/api/v1/travels/{travelId}/map-points', coreSlo: true },
  { id: 'routeGet', weight: 3, family: 'routes-mock', service: 'maps', domain: 'routes', subdomain: 'maps-routes', method: 'GET', route: '/api/v1/travels/{travelId}/routes', coreSlo: true },
  { id: 'routePreview', weight: 3, family: 'routes-mock', service: 'maps', domain: 'routes', subdomain: 'maps-routes', method: 'POST', route: '/api/v1/travels/{travelId}/routes/preview', coreSlo: true },
  { id: 'timelineCreate', weight: 8, family: 'timeline-write', service: 'travel', domain: 'timeline', subdomain: 'travel-timeline', method: 'POST', route: '/api/v1/travels/{travelId}/timeline-items', coreSlo: true },
  { id: 'orderChange', weight: 6, family: 'timeline-write', service: 'travel', domain: 'timeline', subdomain: 'travel-timeline', method: 'PATCH', route: '/api/v1/travels/{travelId}/timeline-items/order', coreSlo: true },
  { id: 'memberList', weight: 3, family: 'travel-read', service: 'travel', domain: 'membership', subdomain: 'travel-membership', method: 'GET', route: '/api/v1/travels/{travelId}/members', coreSlo: true },
  { id: 'invitationList', weight: 3, family: 'travel-read', service: 'travel', domain: 'membership', subdomain: 'travel-membership', method: 'GET', route: '/api/v1/users/me/travel-invitations', coreSlo: true },
  { id: 'communityCategoryList', weight: 2, family: 'community-read', service: 'community', domain: 'community', subdomain: 'community-read', method: 'GET', route: '/api/v1/community/categories', coreSlo: true },
  { id: 'communityPostList', weight: 8, family: 'community-read', service: 'community', domain: 'community', subdomain: 'community-read', method: 'GET', route: '/api/v1/community/posts', coreSlo: true },
  { id: 'communityPostDetail', weight: 5, family: 'community-read', service: 'community', domain: 'community', subdomain: 'community-read', method: 'GET', route: '/api/v1/community/posts/{postId}', coreSlo: true },
  { id: 'communityCommentList', weight: 4, family: 'community-read', service: 'community', domain: 'community', subdomain: 'community-read', method: 'GET', route: '/api/v1/community/posts/{postId}/comments', coreSlo: true },
  { id: 'communityMyPosts', weight: 2, family: 'community-read', service: 'community', domain: 'community', subdomain: 'community-read', method: 'GET', route: '/api/v1/community/me/posts', coreSlo: true },
  { id: 'communityMyComments', weight: 1, family: 'community-read', service: 'community', domain: 'community', subdomain: 'community-read', method: 'GET', route: '/api/v1/community/me/comments', coreSlo: true },
  { id: 'communityPostUpdate', weight: 3, family: 'community-write', service: 'community', domain: 'community', subdomain: 'community-write', method: 'PATCH', route: '/api/v1/community/posts/{postId}', coreSlo: true },
  { id: 'communityCommentUpdate', weight: 3, family: 'community-write', service: 'community', domain: 'community', subdomain: 'community-write', method: 'PATCH', route: '/api/v1/community/comments/{commentId}', coreSlo: true },
  { id: 'communityPostReaction', weight: 3, family: 'community-write', service: 'community', domain: 'community', subdomain: 'community-write', method: 'PUT', route: '/api/v1/community/posts/{postId}/reactions/{type}', coreSlo: true },
  { id: 'communityCommentReaction', weight: 3, family: 'community-write', service: 'community', domain: 'community', subdomain: 'community-write', method: 'PUT', route: '/api/v1/community/comments/{commentId}/reactions/{type}', coreSlo: true },
];

const OPERATION_BY_ID = Object.fromEntries(CURRENT_FEATURE_OPERATIONS.map((item) => [item.id, item]));
const TOTAL_WEIGHT = CURRENT_FEATURE_OPERATIONS.reduce((sum, item) => sum + item.weight, 0);
if (TOTAL_WEIGHT !== 100) throw new Error(`current-feature operation weights must sum to 100 (got ${TOTAL_WEIGHT})`);

// Fixed metric names keep the raw evidence bounded and make the observed vs
// expected mix exportable without adding unbounded operation/request labels.
export const operationSelectionCounters = {};
export const operationContractFailureCounters = {};
// Emitted before the first HTTP call in each selected operation.  The AWS
// wrapper uses the first point from this counter as the actual workload
// dispatch timestamp; shell/container start time is only a preparation time.
export const operationStartedCounter = new Counter('aws_operation_started_total');
for (const operation of CURRENT_FEATURE_OPERATIONS) {
  operationSelectionCounters[operation.id] = new Counter(`aws_operation_${operation.id}_selected_total`);
  operationContractFailureCounters[operation.id] = new Counter(`aws_operation_${operation.id}_contract_failures_total`);
}

function tags(operationId) {
  const operation = OPERATION_BY_ID[operationId];
  return {
    name: operationId,
    flow: 'current-feature',
    operationId,
    featureFamily: operation.family,
    service: operation.service,
    domain: operation.domain,
    subdomain: operation.subdomain,
  };
}

function jsonBody(response) {
  try {
    return response.json();
  } catch (_) {
    return null;
  }
}

function dataOf(response) {
  const body = jsonBody(response);
  return body && typeof body === 'object' ? body.data : null;
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isPage(value) {
  return isObject(value) && Array.isArray(value.content);
}

function isSuccessfulData(response, predicate) {
  if (response.status < 200 || response.status >= 300) return false;
  return predicate ? predicate(dataOf(response), response) : true;
}

function requestOperation(
  operationId,
  method,
  path,
  body = null,
  expected = [200],
  predicate = null,
  requiresAuth = true,
) {
  const request = (headers) => http.request(
    method,
    `${API}${path}`,
    body === null ? null : JSON.stringify(body),
    {
      headers: requiresAuth ? headers : { 'Content-Type': 'application/json' },
      tags: tags(operationId),
    },
  );
  const response = requiresAuth
    ? withAuthRetry(request)
    : request({});
  record(response, { expect: expected });
  const contractOk = expected.includes(response.status) && isSuccessfulData(response, predicate);
  if (!contractOk) operationContractFailureCounters[operationId].add(1, tags(operationId));
  check(response, { [`${operationId} contract`]: () => contractOk });
  return response;
}

function marker() {
  return fixtureMarker()
    || String(__ENV.RUN_ID || 'scrum80').replace(/[^A-Za-z0-9-]/g, '-').slice(-32);
}

function firstPlaceId() {
  return placeIds()[0] || `loadtest-${marker()}-place-001`;
}

function routeWaypoints() {
  const ids = placeIds();
  const selected = ids.length >= 3 ? ids.slice(0, 3) : [firstPlaceId(), `loadtest-${marker()}-place-002`, `loadtest-${marker()}-place-003`];
  return selected.map((googlePlaceId, index) => ({
    googlePlaceId,
    latitude: 35.681236 + index * 0.01,
    longitude: 139.767125 + index * 0.01,
  }));
}

export function profileRead() {
  return requestOperation('profileRead', 'GET', '/users/me/profile', null, [200], isObject);
}

export function travelList() {
  return requestOperation('travelList', 'GET', '/travels', null, [200], isPage);
}

export function travelDetail() {
  return requestOperation('travelDetail', 'GET', `/travels/${travelId()}`, null, [200], isObject);
}

export function travelUpdate() {
  const response = requestOperation(
    'travelUpdate',
    'PATCH',
    `/travels/${travelId()}`,
    { title: `LoadTest ${marker()} ${exec.vu.idInTest}`, version: travelVersion() },
    [200],
    (data) => isObject(data) && Number.isInteger(data.version),
  );
  const data = dataOf(response);
  if (response.status === 200 && data && Number.isInteger(data.version)) setTravelVersion(data.version);
  return response;
}

export function countryList() {
  return requestOperation('countryList', 'GET', '/countries', null, [200], (data) => Array.isArray(data));
}

export function cityList() {
  return requestOperation('cityList', 'GET', '/countries/1/cities', null, [200], (data) => Array.isArray(data));
}

export function placeSearch() {
  return requestOperation(
    'placeSearch',
    'GET',
    '/places/search?query=Tokyo%20Tower&countryCode=JP',
    null,
    [200],
    (data) => Array.isArray(data) && data.length > 0,
  );
}

export function nearbySearch() {
  return requestOperation(
    'nearbySearch',
    'GET',
    '/places/nearby?latitude=35.681236&longitude=139.767125&radiusMeters=1500',
    null,
    [200],
    (data) => Array.isArray(data) && data.length > 0,
  );
}

export function mapPoints() {
  return requestOperation(
    'mapPoints',
    'GET',
    `/travels/${travelId()}/map-points?dayNumber=1`,
    null,
    [200],
    (data) => isObject(data) && Array.isArray(data.points),
  );
}

export function routeGet() {
  return requestOperation(
    'routeGet',
    'GET',
    `/travels/${travelId()}/routes?dayNumber=1&transportationType=DRIVE`,
    null,
    [200],
    (data) => isObject(data),
  );
}

export function routePreview() {
  return requestOperation(
    'routePreview',
    'POST',
    `/travels/${travelId()}/routes/preview`,
    { dayNumber: 1, transportationType: 'TRANSIT', waypoints: routeWaypoints() },
    [200],
    (data) => isObject(data) && Array.isArray(data.encodedPolylines),
  );
}

export function timelineCreate() {
  const response = requestOperation(
    'timelineCreate',
    'POST',
    `/travels/${travelId()}/timeline-items`,
    {
      // Keep the create operation representative without growing the day-1
      // route fixture on every arrival.  An unassigned item is a supported
      // backend state (dayNumber and visitDate are both null); the seeded
      // three-item day-1 fixture remains the stable input for routeGet and
      // orderChange throughout a long Baseline/stress run.
      dayNumber: null,
      visitDate: null,
      category: '관광지',
      name: `load-${marker()}-${exec.vu.idInTest}-${exec.scenario.iterationInTest}`,
      googlePlaceId: firstPlaceId(),
      visitOrder: nextVisitOrder(),
    },
    [200, 201],
    (data) => isObject(data) && typeof data.timelineItemId === 'string',
  );
  return response;
}

export function orderChange() {
  const itemIds = timelineItemIds();
  if (itemIds.length < 2) throw new Error('orderChange requires at least two seeded timeline items');
  return requestOperation(
    'orderChange',
    'PATCH',
    `/travels/${travelId()}/timeline-items/order`,
    { dayNumber: 1, items: itemIds.slice().reverse().map((itemId, index) => ({ itemId, visitOrder: index + 1 })) },
    [200, 204],
    () => true,
  );
}

export function memberList() {
  return requestOperation('memberList', 'GET', `/travels/${travelId()}/members`, null, [200], (data) => Array.isArray(data));
}

export function invitationList() {
  return requestOperation(
    'invitationList',
    'GET',
    '/users/me/travel-invitations?status=PENDING&page=0&size=20',
    null,
    [200],
    isPage,
  );
}

export function communityCategoryList() {
  return requestOperation('communityCategoryList', 'GET', '/community/categories?excludeNotice=true', null, [200], (data) => Array.isArray(data), false);
}

export function communityPostList() {
  return requestOperation('communityPostList', 'GET', '/community/posts?size=20&page=0', null, [200], isPage, false);
}

export function communityPostDetail() {
  return requestOperation('communityPostDetail', 'GET', `/community/posts/${postId()}`, null, [200], isObject, false);
}

export function communityCommentList() {
  return requestOperation('communityCommentList', 'GET', `/community/posts/${postId()}/comments`, null, [200], (data) => Array.isArray(data), false);
}

export function communityMyPosts() {
  return requestOperation('communityMyPosts', 'GET', `/community/me/posts?keyword=${encodeURIComponent(marker())}&size=20&page=0`, null, [200], isPage);
}

export function communityMyComments() {
  return requestOperation('communityMyComments', 'GET', `/community/me/comments?keyword=${encodeURIComponent(marker())}&size=20&page=0`, null, [200], isPage);
}

export function communityPostUpdate() {
  const response = requestOperation(
    'communityPostUpdate',
    'PATCH',
    `/community/posts/${postId()}`,
    { title: `LoadTest ${marker()} updated`, version: postVersion() },
    [200],
    (data) => isObject(data) && Number.isInteger(data.version),
  );
  const data = dataOf(response);
  if (response.status === 200 && data && Number.isInteger(data.version)) setPostVersion(data.version);
  return response;
}

export function communityCommentUpdate() {
  return requestOperation(
    'communityCommentUpdate',
    'PATCH',
    `/community/comments/${commentId()}`,
    { content: `LoadTest ${marker()} comment ${commentSequence()}` },
    [200],
    (data) => isObject(data) && typeof data.commentId === 'string',
  );
}

export function communityPostReaction() {
  return requestOperation('communityPostReaction', 'PUT', `/community/posts/${postId()}/reactions/LIKE`, null, [200], isObject);
}

export function communityCommentReaction() {
  return requestOperation('communityCommentReaction', 'PUT', `/community/comments/${commentId()}/reactions/LIKE`, null, [200], isObject);
}

const FLOWS = {
  profileRead,
  travelList,
  travelDetail,
  travelUpdate,
  countryList,
  cityList,
  placeSearch,
  nearbySearch,
  mapPoints,
  routeGet,
  routePreview,
  timelineCreate,
  orderChange,
  memberList,
  invitationList,
  communityCategoryList,
  communityPostList,
  communityPostDetail,
  communityCommentList,
  communityMyPosts,
  communityMyComments,
  communityPostUpdate,
  communityCommentUpdate,
  communityPostReaction,
  communityCommentReaction,
};

function refresh() {
  const token = accessToken({ forceRefresh: true });
  const ok = typeof token === 'string' && token.length > 0;
  if (!ok) operationContractFailureCounters.refresh.add(1, tags('refresh'));
  check({ token }, { 'refresh contract': (value) => typeof value.token === 'string' && value.token.length > 0 });
  return token;
}

function markSelection(operationId) {
  const operation = OPERATION_BY_ID[operationId];
  if (!operation) throw new Error(`unsupported current-feature operation: ${operationId}`);
  operationStartedCounter.add(1, tags(operationId));
  operationSelectionCounters[operationId].add(1, tags(operationId));
}

export function runCurrentOperation(operationId) {
  markSelection(operationId);
  if (operationId === 'refresh') return refresh();
  return recordCoreOperation(FLOWS[operationId]);
}

export function chooseCurrentOperation(mix) {
  const draw = Math.random() * 100;
  let cursor = 0;
  for (const operation of CURRENT_FEATURE_OPERATIONS) {
    cursor += Number(mix[operation.id] ?? operation.weight);
    if (draw < cursor) return operation.id;
  }
  return CURRENT_FEATURE_OPERATIONS[CURRENT_FEATURE_OPERATIONS.length - 1].id;
}

export function runMixedCurrentOperation(mix) {
  return runCurrentOperation(chooseCurrentOperation(mix));
}

export function operationMixSummary(metrics, expectedMix) {
  const output = {};
  for (const operation of CURRENT_FEATURE_OPERATIONS) {
    const metric = metrics[`aws_operation_${operation.id}_selected_total`];
    const count = metric && metric.values ? Number(metric.values.count || 0) : 0;
    output[operation.id] = {
      featureFamily: operation.family,
      service: operation.service,
      domain: operation.domain,
      subdomain: operation.subdomain,
      expectedWeight: Number(expectedMix[operation.id] ?? operation.weight),
      observedCount: count,
      observedWeight: null,
    };
  }
  const total = Object.values(output).reduce((sum, item) => sum + item.observedCount, 0);
  Object.values(output).forEach((item) => {
    item.observedWeight = total > 0 ? (item.observedCount / total) * 100 : null;
  });
  return { totalSelections: total, operations: output };
}

// Used by tests and the AWS summary handler; no random operation IDs are
// exported as metric labels, keeping Prometheus cardinality bounded.
export function registeredOperationIds() {
  return CURRENT_FEATURE_OPERATIONS.map((operation) => operation.id);
}

// Keep hotspot mixes deterministic and proportional to the frozen normal mix.
// A candidate is a domain/subdomain name (or an operation id), so the same
// helper can drive both service-level and endpoint-level diagnostics without
// introducing unbounded metric labels.
export function buildHotspotMix(baseMix, candidate, hotspotShare = 60) {
  const share = Number(hotspotShare);
  if (!Number.isFinite(share) || share <= 0 || share >= 100) {
    throw new Error('hotspotShare must be between 0 and 100');
  }
  const selected = CURRENT_FEATURE_OPERATIONS.filter((operation) => (
    operation.id === candidate
      || operation.service === candidate
      || operation.domain === candidate
      || operation.subdomain === candidate
  ));
  if (selected.length === 0) throw new Error(`unknown hotspot candidate: ${candidate}`);
  const selectedIds = new Set(selected.map((operation) => operation.id));
  const weights = {};
  let hotspotTotal = 0;
  let backgroundTotal = 0;
  for (const operation of CURRENT_FEATURE_OPERATIONS) {
    const weight = Number(baseMix[operation.id] ?? operation.weight);
    if (!Number.isFinite(weight) || weight < 0) throw new Error(`invalid base mix for ${operation.id}`);
    if (selectedIds.has(operation.id)) hotspotTotal += weight;
    else backgroundTotal += weight;
  }
  if (hotspotTotal <= 0 || backgroundTotal <= 0) throw new Error(`hotspot candidate has no proportional background: ${candidate}`);
  for (const operation of CURRENT_FEATURE_OPERATIONS) {
    const weight = Number(baseMix[operation.id] ?? operation.weight);
    weights[operation.id] = selectedIds.has(operation.id)
      ? (weight / hotspotTotal) * share
      : (weight / backgroundTotal) * (100 - share);
  }
  return weights;
}

// Keep these imports/exports exercised by the static JS loader even when a
// smoke run has not yet created a new timeline item or fixture state.
void registerPlaceIds;
void registerPost;
void registerComment;
