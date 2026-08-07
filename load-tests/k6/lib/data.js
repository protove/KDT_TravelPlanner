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

const vuStates = {};

export function vuCredential() {
  return credentials[(exec.vu.idInTest - 1) % credentials.length];
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
