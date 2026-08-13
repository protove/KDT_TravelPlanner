// Compose rehearsal configuration. Values are deliberately not AWS SLOs.
export const BASE_URL = __ENV.BASE_URL || 'http://host.docker.internal:8080';
export const API = `${BASE_URL}/api/v1`;

export const SLO = {
  P95_MS: 500,
  UNEXPECTED_ERROR_RATE: 0.01,
  CONTRACT_FAILURE_RATE: 0.01,
  SUCCESS_DELIVERY_RATE: 0.99,
};
