// Core API operation counters required by
// aws-load-test-handoff/contracts/SLO_AND_METRIC_CONTRACT.md:
//   core_operations_total, core_completed_operations_total,
//   core_successful_operations_total, core_unexpected_errors_total,
//   core_contract_failures_total.
//
// This module does not duplicate or modify the existing flow functions in
// ../../flows/*.js. It wraps a call to an existing flow function and reads
// the classification that ../../lib/metrics.js record() already computed for
// that call, via consumeLastRecord(). Auth-refresh calls
// (lib/auth.js accessToken()) are excluded from the Core API denominator by
// construction: AWS scenarios call accessToken() directly for forced
// refresh, never through recordCoreOperation(), so refresh calls never reach
// these counters.
import { Counter } from 'k6/metrics';
import { consumeLastRecord } from '../../lib/metrics.js';

export const coreOperations = new Counter('core_operations_total');
export const coreCompletedOperations = new Counter('core_completed_operations_total');
export const coreSuccessfulOperations = new Counter('core_successful_operations_total');
export const coreUnexpectedErrors = new Counter('core_unexpected_errors_total');
export const coreContractFailures = new Counter('core_contract_failures_total');

// Wraps a Core API flow call (e.g. travelList, travelDetail, mapPoints,
// timelineCreate) and records it against the core_* counters using the
// outcome the flow's own record() call already produced. If the flow
// returns without calling record() at all (e.g. timeline-write.js
// orderChange() when fewer than two timeline items exist yet), no HTTP
// request happened, so nothing is counted — this matches the contract's
// "completed operation" definition, which requires an observed final
// response or transport timeout.
export function recordCoreOperation(flowFn, ...args) {
  consumeLastRecord(); // clear any leftover classification before this call
  const result = flowFn(...args);
  const outcome = consumeLastRecord();
  if (!outcome) return result;

  coreOperations.add(1);
  if (outcome.completed) coreCompletedOperations.add(1);
  if (outcome.isExpected) coreSuccessfulOperations.add(1);
  if (outcome.isTransportFailure || outcome.isServerFailure) coreUnexpectedErrors.add(1);
  if (outcome.isContractFailure) coreContractFailures.add(1);
  return result;
}
