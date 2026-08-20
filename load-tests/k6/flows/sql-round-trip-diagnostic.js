import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';
import { API } from '../lib/config.js';
import { vuCredential } from '../lib/data.js';
import { record } from '../lib/metrics.js';

export const sqlDiagnosticItemCount = new Trend('sql_diagnostic_item_count');
export const sqlDiagnosticRequestBodyBytes = new Trend('sql_diagnostic_request_body_bytes');
export const sqlDiagnosticSuccessfulRequests = new Counter('sql_diagnostic_successful_requests');
export const sqlDiagnosticContractFailures = new Rate('sql_diagnostic_contract_failures');

const state = { reverseFlip: false };

function config() {
  const mode = __ENV.SQL_DIAG_MODE;
  const itemCount = Number(__ENV.SQL_DIAG_ITEM_COUNT);
  const credential = vuCredential();
  const stage = credential.sqlDiagnosticStages?.[`${mode}-${itemCount}`];
  if (!stage || !Array.isArray(stage.timelineItemIds) || stage.timelineItemIds.length !== itemCount) {
    throw new Error(`SQL diagnostic fixture missing ${mode}-${itemCount}`);
  }
  return { mode, itemCount, credential, stage };
}

function requestTags(stageConfig) {
  return {
    name: 'timelineOrderSqlDiagnostic',
    flow: 'sql-round-trip-diagnostic',
    sql_diagnostic_mode: stageConfig.mode,
    sql_diagnostic_item_count: String(stageConfig.itemCount),
  };
}

function orderIds(stageConfig) {
  const canonical = stageConfig.stage.timelineItemIds;
  if (stageConfig.mode === 'noop') return canonical.slice();
  const ids = state.reverseFlip ? canonical.slice() : canonical.slice().reverse();
  state.reverseFlip = !state.reverseFlip;
  return ids;
}

export function runSqlDiagnosticIteration() {
  const stageConfig = config();
  const ids = orderIds(stageConfig);
  const items = ids.map((itemId, index) => ({ itemId, visitOrder: index + 1 }));
  const body = JSON.stringify({ dayNumber: 1, items });
  const tags = requestTags(stageConfig);
  sqlDiagnosticItemCount.add(stageConfig.itemCount, tags);
  sqlDiagnosticRequestBodyBytes.add(body.length, tags);
  const response = http.patch(
    `${API}/travels/${stageConfig.stage.travelId}/timeline-items/order`,
    body,
    { headers: { Authorization: `Bearer ${stageConfig.credential.accessToken}`, 'Content-Type': 'application/json' }, tags },
  );
  const result = record(response, { expect: [200] });
  const ok = response.status === 200;
  sqlDiagnosticContractFailures.add(ok ? 0 : 1, tags);
  if (ok) sqlDiagnosticSuccessfulRequests.add(1, tags);
  check(response, { 'sql diagnostic reorder 200': (candidate) => candidate.status === 200 });
  sleep(Number(__ENV.SQL_DIAG_PACING_SECONDS || '0.25'));
  return { response, result, itemCount: stageConfig.itemCount, mode: stageConfig.mode };
}
