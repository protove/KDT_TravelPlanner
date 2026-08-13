import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL } from './config.js';

const tokenCache = {};

export function getAccessToken(account) {
  const cacheKey = account.refreshToken || 'default';
  if (tokenCache[cacheKey]) return tokenCache[cacheKey];

  const res = http.post(`${BASE_URL}/api/v1/auth/token/refresh`, null, {
    cookies: {
      refresh_token: account.refreshToken,
    },
  });

  const ok = check(res, {
    'auth refresh 200': (r) => r.status === 200,
    'auth refresh has accessToken': (r) => {
      try {
        return !!JSON.parse(r.body).data.accessToken;
      } catch (e) {
        return false;
      }
    },
  });

  if (!ok) return null;

  const accessToken = JSON.parse(res.body).data.accessToken;
  tokenCache[cacheKey] = accessToken;
  return accessToken;
}

export function authHeaders(accessToken) {
  return {
    Authorization: `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
  };
}
