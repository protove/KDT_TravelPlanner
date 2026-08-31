// AWS smoke scenario. Exercise every current-feature operation once per VU so
// endpoint and private Google-mock contracts are proven before arrival-rate
// traffic starts.
import { registeredOperationIds, runCurrentOperation } from '../flows/current-feature-operations.js';
import { smokeThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';

export const options = {
  scenarios: {
    smoke: { executor: 'per-vu-iterations', vus: 2, iterations: 1, maxDuration: '2m' },
  },
  thresholds: smokeThresholds,
};

export default function smoke() {
  registeredOperationIds().forEach((operationId) => runCurrentOperation(operationId));
}

export const handleSummary = makeAwsSummaryHandler('aws-smoke');
