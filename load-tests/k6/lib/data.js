import { SharedArray } from 'k6/data';
import exec from 'k6/execution';

const credentials = new SharedArray('load-test-credentials', () => {
  const file = __ENV.DATA_FILE || '../data/data.json';
  const parsed = JSON.parse(open(file));
  if (!parsed.credentials || parsed.credentials.length === 0) {
    throw new Error('load-test data must contain at least one credential');
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
