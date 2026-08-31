import { SharedArray } from 'k6/data';
import exec from 'k6/execution';

const credentials = new SharedArray('load-test-credentials', () => {
  const file = __ENV.DATA_FILE || '../data/data.json';
  const parsed = JSON.parse(open(file));
  if (!parsed.credentials || parsed.credentials.length === 0) {
    throw new Error('load-test data must contain at least one credential');
  }
  if (__ENV.REQUIRE_UNIQUE_CREDENTIALS === '1' && parsed.seedState !== 'complete') {
    throw new Error('AWS load-test data seedState must be complete');
  }
  return parsed.credentials;
});

if (__ENV.REQUIRE_UNIQUE_CREDENTIALS === '1') {
  const requiredCredentialCount = Number(__ENV.REQUIRED_UNIQUE_CREDENTIAL_COUNT);
  if (!Number.isInteger(requiredCredentialCount) || requiredCredentialCount < 1) {
    throw new Error('REQUIRED_UNIQUE_CREDENTIAL_COUNT must be a positive integer');
  }
  if (credentials.length < requiredCredentialCount) {
    throw new Error(
      `seeded credential count ${credentials.length} is smaller than `
      + `required unique credential count ${requiredCredentialCount}`,
    );
  }
}

const vuStates = {};

export function vuCredential() {
  const credentialIndex = exec.vu.idInTest - 1;
  if (__ENV.REQUIRE_UNIQUE_CREDENTIALS === '1') {
    if (credentialIndex >= credentials.length) {
      throw new Error(
        `AWS VU ${exec.vu.idInTest} has no unique credential; `
        + `seeded credential count is ${credentials.length}`,
      );
    }
    return credentials[credentialIndex];
  }
  return credentials[credentialIndex % credentials.length];
}

function vuState() {
  const vuId = exec.vu.idInTest;
  if (!vuStates[vuId]) {
    const credential = vuCredential();
    vuStates[vuId] = {
      timelineItemIds: (credential.timelineItemIds || []).slice(),
      placeIds: (credential.placeIds || credential.googlePlaceIds || []).slice(),
      postId: credential.postId || null,
      commentId: credential.commentId || null,
      fixtureMarker: credential.fixtureMarker || null,
      travelVersion: Number.isInteger(credential.travelVersion) ? credential.travelVersion : 0,
      postVersion: Number.isInteger(credential.postVersion) ? credential.postVersion : 0,
      commentSequence: Number.isInteger(credential.commentSequence) ? credential.commentSequence : 0,
      nextVisitOrder: (credential.timelineItemIds || []).length + 1,
    };
  }
  return vuStates[vuId];
}

export function travelId() {
  return vuCredential().travelId;
}

export function visitDate() {
  return vuCredential().visitDate;
}

export function timelineItemIds() {
  return vuState().timelineItemIds.slice();
}

export function nextVisitOrder() {
  const state = vuState();
  const visitOrder = state.nextVisitOrder;
  state.nextVisitOrder += 1;
  return visitOrder;
}

export function registerTimelineItem(timelineItemId) {
  if (timelineItemId) vuState().timelineItemIds.push(timelineItemId);
}

export function placeIds() {
  return vuState().placeIds.slice();
}

export function postId() {
  return vuState().postId;
}

export function commentId() {
  return vuState().commentId;
}

export function fixtureMarker() {
  return vuState().fixtureMarker || null;
}

export function travelVersion() {
  return vuState().travelVersion;
}

export function postVersion() {
  return vuState().postVersion;
}

export function commentSequence() {
  const state = vuState();
  const value = state.commentSequence;
  state.commentSequence += 1;
  return value;
}

export function registerPlaceIds(ids) {
  if (Array.isArray(ids)) vuState().placeIds = ids.filter(Boolean).slice();
}

export function registerPost(post) {
  if (!post) return;
  const state = vuState();
  if (typeof post === 'string') {
    state.postId = post;
    return;
  }
  if (post.postId) state.postId = post.postId;
  if (Number.isInteger(post.version)) state.postVersion = post.version;
}

export function registerComment(comment) {
  if (!comment) return;
  const state = vuState();
  if (typeof comment === 'string') {
    state.commentId = comment;
    return;
  }
  if (comment.commentId) state.commentId = comment.commentId;
}

export function setTravelVersion(version) {
  if (Number.isInteger(version)) vuState().travelVersion = version;
}

export function setPostVersion(version) {
  if (Number.isInteger(version)) vuState().postVersion = version;
}
