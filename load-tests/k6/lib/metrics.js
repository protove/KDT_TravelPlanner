import { Counter, Rate } from 'k6/metrics';

export const unexpectedErrors = new Rate('unexpected_errors');
export const contractFail = new Rate('contract_fail');
export const expected4xx = new Counter('expected_4xx');
export const successfulRequests = new Counter('successful_requests');

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
  return response;
}
