import { runSqlDiagnosticIteration } from '../flows/sql-round-trip-diagnostic.js';
import { makeSummaryHandler } from '../summary.js';

const iterations = Number(__ENV.SQL_DIAG_ITERATIONS || '30');
if (!Number.isInteger(iterations) || iterations < 1) throw new Error('SQL_DIAG_ITERATIONS must be positive');

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    sqlDiagnostic: {
      executor: 'shared-iterations',
      vus: 1,
      iterations,
      maxDuration: '10m',
      exec: 'sqlDiagnostic',
    },
  },
  thresholds: {
    http_req_failed: ['rate==0'],
    unexpected_errors: ['rate==0'],
    contract_fail: ['rate==0'],
    sql_diagnostic_contract_failures: ['rate==0'],
    sql_diagnostic_successful_requests: [`count==${iterations}`],
  },
};

export function sqlDiagnostic() {
  runSqlDiagnosticIteration();
}

export const handleSummary = makeSummaryHandler(
  `sql-round-trip:${__ENV.SQL_DIAG_MODE || 'unknown'}:${__ENV.SQL_DIAG_ITEM_COUNT || 'unknown'}`,
);
