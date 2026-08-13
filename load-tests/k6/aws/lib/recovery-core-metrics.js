// Recovery-only Core API counters and duration. The B-01 core-metrics module
// remains untouched so the Recovery Trend cannot alter an in-flight B-01 run.
import { Counter, Trend } from 'k6/metrics';
import { consumeLastRecord } from '../../lib/metrics.js';

export const coreOperations = new Counter('core_operations_total');
export const coreCompletedOperations = new Counter('core_completed_operations_total');
export const coreSuccessfulOperations = new Counter('core_successful_operations_total');
export const coreUnexpectedErrors = new Counter('core_unexpected_errors_total');
export const coreContractFailures = new Counter('core_contract_failures_total');
export const coreOperationDuration = new Trend('core_operation_duration', true);

export function recordCoreOperation(flowFn, ...args) {
  consumeLastRecord();
  const startedAt = Date.now();
  const result = flowFn(...args);
  const outcome = consumeLastRecord();
  if (!outcome) return result;

  coreOperations.add(1);
  coreOperationDuration.add(Date.now() - startedAt);
  if (outcome.completed) coreCompletedOperations.add(1);
  if (outcome.isExpected) coreSuccessfulOperations.add(1);
  if (outcome.isTransportFailure || outcome.isServerFailure) coreUnexpectedErrors.add(1);
  if (outcome.isContractFailure) coreContractFailures.add(1);
  return result;
}
