import { Counter, Rate } from 'k6/metrics';

export const unexpectedErrors = new Rate('unexpected_errors');
export const contractFail = new Rate('contract_fail');
export const expected4xx = new Counter('expected_4xx');
export const successfulRequests = new Counter('successful_requests');

// Classification of the most recent record() call on this VU. This is a
// read-only observation point for callers that need to know what record()
// just decided (e.g. AWS core-operation counters in load-tests/k6/aws/lib).
// It does not change any existing counter/rate value or Compose scenario
// output; nothing before this change read lastRecord.
export let lastRecord = null;

export function record(response, { expect = [200, 201, 204], allowDomain4xx = false } = {}) {
  const isTransportFailure = response.status === 0;
  const isServerFailure = response.status >= 500;
  const isExpected = expect.includes(response.status);
  const isDomain4xx = response.status >= 400 && response.status < 500 && !isExpected;
  const isContractFailure = !isExpected && !(allowDomain4xx && isDomain4xx);

  unexpectedErrors.add(isTransportFailure || isServerFailure);
  contractFail.add(isContractFailure);
  if (isExpected) successfulRequests.add(1);
  if (isDomain4xx) expected4xx.add(1);

  lastRecord = {
    completed: true,
    isTransportFailure,
    isServerFailure,
    isExpected,
    isDomain4xx,
    isContractFailure,
  };

  return response;
}

// Reads and clears lastRecord in one step so a caller can tell "record() ran
// during my last call" apart from "record() did not run" (e.g. a flow
// function that returns early without an HTTP call). Imported `let` bindings
// are read-only from other modules, so external code cannot reset
// lastRecord itself; this function is the only supported way to consume it.
export function consumeLastRecord() {
  const value = lastRecord;
  lastRecord = null;
  return value;
}
