// AWS summary handler. Extends the Compose ../summary.js pattern with the
// core_* Core API operation counters and AWS run identity fields required by
// aws-load-test-handoff/plans/01_AWS_K6_WORKLOAD_PLAN.md and
// contracts/RUN_METADATA_CONTRACT.md. Does not modify ../summary.js, which
// Compose scenarios continue to use unchanged.
import {
  ENVIRONMENT, REGION, REQUEST_MIX_VERSION, SEED_VERSION, SLO_CONTRACT_VERSION, SLO_VERSION,
} from './config.js';

export function makeAwsSummaryHandler(scenarioName) {
  return function handleSummary(data) {
    const metrics = data.metrics || {};
    const metricValues = (name, fallback = {}) => metrics[name]?.values || fallback;
    const summary = {
      scenario: scenarioName,
      platform: __ENV.TARGET_PLATFORM || 'ec2',
      runId: __ENV.RUN_ID || null,
      startedAtUtc: __ENV.RUN_STARTED_AT || null,
      region: REGION,
      environment: ENVIRONMENT,
      sloVersion: SLO_VERSION,
      sloContractVersion: SLO_CONTRACT_VERSION,
      seedVersion: SEED_VERSION,
      requestMixVersion: REQUEST_MIX_VERSION,
      metrics: {
        http_reqs: metricValues('http_reqs'),
        http_req_duration: metricValues('http_req_duration'),
        unexpected_errors: metricValues('unexpected_errors'),
        contract_fail: metricValues('contract_fail'),
        successful_requests: metricValues('successful_requests'),
        expected_4xx: metricValues('expected_4xx', { count: 0, rate: 0 }),
        dropped_iterations: metricValues('dropped_iterations', { count: 0, rate: 0 }),
        checks: metricValues('checks'),
        core_operations_total: metricValues('core_operations_total', { count: 0 }),
        core_completed_operations_total: metricValues('core_completed_operations_total', { count: 0 }),
        core_successful_operations_total: metricValues('core_successful_operations_total', { count: 0 }),
        core_unexpected_errors_total: metricValues('core_unexpected_errors_total', { count: 0 }),
        core_contract_failures_total: metricValues('core_contract_failures_total', { count: 0 }),
      },
      thresholds: Object.fromEntries(Object.entries(metrics)
        .filter(([, metric]) => metric.thresholds)
        .map(([name, metric]) => [name, Object.fromEntries(
          Object.entries(metric.thresholds).map(([threshold, value]) => [threshold, value.ok]),
        )])),
    };
    const outputDirectory = __ENV.OUT_DIR || '.';
    return {
      [`${outputDirectory}/summary.json`]: JSON.stringify(summary, null, 2),
      stdout: textSummary(summary),
    };
  };
}

function safeRate(numerator, denominator) {
  if (!denominator) return null;
  return numerator / denominator;
}

function textSummary(summary) {
  const duration = summary.metrics.http_req_duration || {};
  const completed = summary.metrics.core_completed_operations_total.count || 0;
  const coreErrors = summary.metrics.core_unexpected_errors_total.count || 0;
  const coreErrorRate = safeRate(coreErrors, completed);
  return `\n[${summary.scenario}] p95=${duration['p(95)'] ?? '-'}ms `
    + `p99=${duration['p(99)'] ?? '-'}ms `
    + `core_completed=${completed} `
    + `core_unexpected_error_rate=${coreErrorRate !== null ? `${(coreErrorRate * 100).toFixed(2)}%` : '-'} `
    + `http_reqs=${summary.metrics.http_reqs?.count ?? '-'}\n`;
}
