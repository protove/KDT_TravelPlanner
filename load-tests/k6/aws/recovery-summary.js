// Recovery-specific summary handler. It must not import aws/summary.js,
// because that handler loads the B-01 profile/config at module init time.
import { ENVIRONMENT, REGION, REQUEST_MIX_VERSION, SEED_VERSION, SLO_VERSION } from './recovery-config.js';

function metricValues(metrics, name, fallback = {}) {
  return metrics[name]?.values || fallback;
}

function safeRate(numerator, denominator) {
  return denominator ? numerator / denominator : null;
}

export function makeRecoverySummaryHandler(scenarioName) {
  return function handleSummary(data) {
    const metrics = data.metrics || {};
    const summary = {
      scenario: scenarioName,
      platform: 'ec2',
      runId: __ENV.RUN_ID || null,
      startedAtUtc: __ENV.RUN_STARTED_AT || null,
      region: REGION,
      environment: ENVIRONMENT,
      sloVersion: SLO_VERSION,
      seedVersion: SEED_VERSION,
      requestMixVersion: REQUEST_MIX_VERSION,
      metrics: {
        http_reqs: metricValues(metrics, 'http_reqs'),
        http_req_duration: metricValues(metrics, 'http_req_duration'),
        core_operation_duration: metricValues(metrics, 'core_operation_duration', {}),
        unexpected_errors: metricValues(metrics, 'unexpected_errors'),
        contract_fail: metricValues(metrics, 'contract_fail'),
        successful_requests: metricValues(metrics, 'successful_requests'),
        dropped_iterations: metricValues(metrics, 'dropped_iterations', { count: 0, rate: 0 }),
        core_operations_total: metricValues(metrics, 'core_operations_total', { count: 0 }),
        core_completed_operations_total: metricValues(metrics, 'core_completed_operations_total', { count: 0 }),
        core_successful_operations_total: metricValues(metrics, 'core_successful_operations_total', { count: 0 }),
        core_unexpected_errors_total: metricValues(metrics, 'core_unexpected_errors_total', { count: 0 }),
        core_contract_failures_total: metricValues(metrics, 'core_contract_failures_total', { count: 0 }),
      },
      thresholds: Object.fromEntries(Object.entries(metrics)
        .filter(([, metric]) => metric.thresholds)
        .map(([name, metric]) => [name, Object.fromEntries(
          Object.entries(metric.thresholds).map(([threshold, value]) => [threshold, value.ok]),
        )])),
    };
    const outDir = __ENV.OUT_DIR || '.';
    return {
      [`${outDir}/summary.json`]: JSON.stringify(summary, null, 2),
      stdout: `\n[${scenarioName}] core_completed=${summary.metrics.core_completed_operations_total.count || 0} `
        + `core_unexpected_error_rate=${safeRate(
          summary.metrics.core_unexpected_errors_total.count || 0,
          summary.metrics.core_completed_operations_total.count || 0,
        ) ?? '-'}\n`,
    };
  };
}
