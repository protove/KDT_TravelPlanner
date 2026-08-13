export function makeSummaryHandler(scenarioName) {
  return function handleSummary(data) {
    const metrics = data.metrics || {};
    const metricValues = (name, fallback = {}) => metrics[name]?.values || fallback;
    const summary = {
      scenario: scenarioName,
      runId: __ENV.RUN_ID || null,
      startedAtUtc: __ENV.RUN_STARTED_AT || null,
      sloVersion: 'v0.1-draft',
      metrics: {
        http_reqs: metricValues('http_reqs'),
        http_req_duration: metricValues('http_req_duration'),
        unexpected_errors: metricValues('unexpected_errors'),
        contract_fail: metricValues('contract_fail'),
        successful_requests: metricValues('successful_requests'),
        expected_4xx: metricValues('expected_4xx', { count: 0, rate: 0 }),
        dropped_iterations: metricValues('dropped_iterations', { count: 0, rate: 0 }),
        checks: metricValues('checks'),
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
