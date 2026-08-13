import http from 'k6/http';
import { API } from './config.js';
import { vuCredential } from './data.js';
import { record } from './metrics.js';

const TOKEN_MODE = __ENV.TOKEN_MODE || 'refresh';
let currentRefreshToken = null;
let cachedAccessToken = null;

function rotatedRefreshToken(response) {
  const cookies = response.cookies && response.cookies.refresh_token;
  return cookies && cookies.length > 0 ? cookies[0].value : null;
}

export function accessToken({ forceRefresh = false } = {}) {
  if (cachedAccessToken && !forceRefresh) return cachedAccessToken;

  const credential = vuCredential();
  if (TOKEN_MODE === 'access') {
    cachedAccessToken = credential.accessToken || null;
    return cachedAccessToken;
  }

  if (currentRefreshToken === null) currentRefreshToken = credential.refreshToken;
  const response = http.post(`${API}/auth/token/refresh`, null, {
    headers: { Cookie: `refresh_token=${currentRefreshToken}` },
    tags: { name: 'POST /auth/token/refresh', flow: 'auth' },
  });
  record(response, { expect: [200] });

  if (response.status !== 200) return null;
  const rotated = rotatedRefreshToken(response);
  const nextAccessToken = response.json('data.accessToken');
  if (!rotated || !nextAccessToken) {
    // A successful response without either token is an invalid run, not a retryable 4xx.
    record({ status: 599 }, { expect: [200] });
    return null;
  }
  currentRefreshToken = rotated;
  cachedAccessToken = nextAccessToken;
  return cachedAccessToken;
}

export function authHeaders() {
  const token = accessToken();
  return {
    Authorization: `Bearer ${token || ''}`,
    'Content-Type': 'application/json',
  };
}

export function withAuthRetry(request) {
  let response = request(authHeaders());
  if (response.status === 401) {
    cachedAccessToken = null;
    accessToken({ forceRefresh: true });
    response = request(authHeaders());
  }
  return response;
}
