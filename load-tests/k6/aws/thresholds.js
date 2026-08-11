// AWS k6 thresholds. Values come from
// aws-load-test-handoff/contracts/SLO_AND_METRIC_CONTRACT.md (SLO candidates,
// not yet v1.0-frozen). This does not modify ../config/thresholds.js, which
// Compose scenarios continue to use unchanged.
//
// k6 thresholds can only express pass/fail on a single metric (or a Rate that
// is already a ratio). The contract's core_* SLO ratios
// (core_unexpected_errors_total / core_completed_operations_total, etc.) are
// counter pairs whose denominator excludes auth-refresh calls, which k6's
// threshold DSL cannot express directly. These thresholds therefore gate on
// the same diagnostic Rate metrics Compose already uses (unexpected_errors,
// contract_fail, checks) as an early/local signal. The authoritative core_*
// SLO pass/fail judgement happens later in
// scripts/loadtest/aws/validate-aws-run.py against summary.json, per Plan 03.

import { SLO } from './config.js';

export const smokeThresholds = {
  http_req_duration: [`p(95)<${SLO.P95_MS}`],
  unexpected_errors: [`rate<${SLO.UNEXPECTED_ERROR_RATE}`],
  contract_fail: [`rate<${SLO.CONTRACT_FAILURE_RATE}`],
  checks: ['rate>0.99'],
  dropped_iterations: ['count==0'],
};

export const b01BaselineThresholds = {
  http_req_duration: [`p(95)<${SLO.P95_MS}`],
  unexpected_errors: [`rate<${SLO.UNEXPECTED_ERROR_RATE}`],
  contract_fail: [`rate<${SLO.CONTRACT_FAILURE_RATE}`],
  checks: [`rate>${SLO.SUCCESS_DELIVERY_RATE}`],
  dropped_iterations: ['count==0'],
};

// Ramp is diagnostic: it exists to find the D-005 candidate rate, not to pass
// or fail against the frozen SLO. Overload and runner limits are recorded
// separately, matching the Compose spike.js precedent.
export const b01RampThresholds = {
  dropped_iterations: ['count==0'],
};

// Spike is diagnostic for the same reason the Compose spike.js scenario is:
// intentional overload is expected during the peak hold.
export const b01SpikeThresholds = {};
