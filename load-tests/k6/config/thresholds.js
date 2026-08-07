// Compose rehearsal thresholds. These validate the pipeline, not an AWS SLO.
import { SLO } from '../lib/config.js';

export const rehearsalThresholds = {
  http_req_duration: [`p(95)<${SLO.P95_MS}`],
  unexpected_errors: [`rate<${SLO.UNEXPECTED_ERROR_RATE}`],
  contract_fail: [`rate<${SLO.CONTRACT_FAILURE_RATE}`],
  checks: ['rate>0.99'],
};
