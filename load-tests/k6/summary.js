export function makeSummaryHandler(scenarioName) {
  return function handleSummary(data) {
    const metrics = data.metrics || {};
    const summary = {
      scenario: scenarioName,
      runId: __ENV.RUN_ID || null,
      startedAtUtc: __ENV.RUN_STARTED_AT || null,
      sloVersion: 'v0.1-draft',
      metrics: {
        http_reqs: metrics.http_reqs && metrics.http_reqs.values,
        http_req_duration: metrics.http_req_duration && metrics.http_req_duration.values,
        unexpected_errors: metrics.unexpected_errors && metrics.unexpected_errors.values,
        contract_fail: metrics.contract_fail && metrics.contract_fail.values,
        successful_requests: metrics.successful_requests && metrics.successful_requests.values,
        expected_4xx: metrics.expected_4xx && metrics.expected_4xx.values,
        dropped_iterations: metrics.dropped_iterations && metrics.dropped_iterations.values,
        checks: metrics.checks && metrics.checks.values,
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

function textSummary(summary) {
  const duration = summary.metrics.http_req_duration || {};
  const errors = summary.metrics.unexpected_errors || {};
  return `\n[${summary.scenario}] p95=${duration['p(95)'] ?? '-'}ms `
    + `p99=${duration['p(99)'] ?? '-'}ms `
    + `unexpected=${errors.rate !== undefined ? `${(errors.rate * 100).toFixed(2)}%` : '-'} `
    + `requests=${summary.metrics.http_reqs?.count ?? '-'}\n`;
}
