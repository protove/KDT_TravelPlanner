// AWS k6 config. Loads and validates the AWS profile contract described in
// aws-load-test-handoff/plans/01_AWS_K6_WORKLOAD_PLAN.md. This module does not
// modify or replace ../lib/config.js, which Compose scenarios continue to use
// unchanged.

function fail(message) {
  throw new Error(`[aws/config] ${message}`);
}

function loadProfile() {
  const profilePath = __ENV.AWS_PROFILE_FILE || '../../aws/profiles/ec2-b01.json';
  let raw;
  try {
    raw = open(profilePath);
  } catch (error) {
    fail(`profile file not found: ${profilePath}`);
  }
  let profile;
  try {
    profile = JSON.parse(raw);
  } catch (error) {
    fail(`profile file is not valid JSON: ${profilePath}`);
  }
  return profile;
}

function resolveBaseUrl(profile) {
  // The reused flows import BASE_URL/API from ../lib/config.js, which only
  // ever reads __ENV.BASE_URL (it has no knowledge of this profile file).
  // BASE_URL must therefore be required here, not silently derived from the
  // profile, or this module could validate one target while the flows
  // actually send traffic to a different (or Compose-default) one.
  const envValue = __ENV.BASE_URL;
  if (!envValue) {
    fail('BASE_URL env var is required for AWS runs. The reused flows in '
      + '../lib/config.js read BASE_URL directly and have no access to this '
      + 'profile file, so set BASE_URL to the approved ALB HTTPS origin '
      + 'before running k6.');
  }
  // HTTPS is required for real AWS runs (target must be an approved ALB
  // origin). Local isolated Compose integration testing has no TLS, so the
  // check can only be bypassed by explicitly setting ALLOW_INSECURE_TARGET=1
  // — never the default — mirroring the ALLOW_NON_REHEARSAL_PROJECT pattern
  // scripts/loadtest/run-compose-rehearsal.sh already uses for the same kind
  // of "opt in to break a safety rail for local testing" situation.
  const allowInsecure = __ENV.ALLOW_INSECURE_TARGET === '1';
  if (!allowInsecure && !/^https:\/\//.test(envValue)) {
    fail(`BASE_URL must be HTTPS: ${envValue} (for local Compose integration `
      + 'testing only, set ALLOW_INSECURE_TARGET=1 to allow http://)');
  }
  if (!/^https?:\/\//.test(envValue)) fail(`BASE_URL must be http(s): ${envValue}`);
  if (/REPLACE_/.test(envValue)) fail('BASE_URL is still a placeholder value');

  const profileValue = profile.target && profile.target.baseUrl;
  if (profileValue && !/REPLACE_/.test(profileValue) && profileValue !== envValue) {
    fail(`BASE_URL (${envValue}) does not match profile target.baseUrl `
      + `(${profileValue}); update one so the validated target and the `
      + 'actual request target agree');
  }
  return envValue;
}

function resolveImageDigest(profile) {
  const digest = __ENV.K6_IMAGE_DIGEST || profile.k6Image;
  if (!digest) fail('k6Image digest is missing');
  if (/REPLACE_/.test(digest)) {
    fail('k6Image digest is still a placeholder; set K6_IMAGE_DIGEST or edit the profile');
  }
  if (!/@sha256:[0-9a-f]{64}$/.test(digest)) {
    fail(`k6Image must be pinned by digest (…@sha256:<64 hex>): ${digest}`);
  }
  return digest;
}

function assertGoogleApiDisabled(profile) {
  if (profile.googleApi && profile.googleApi.enabled) {
    fail('googleApi.enabled must be false for AWS load test runs');
  }
}

// SLO candidates from aws-load-test-handoff/contracts/SLO_AND_METRIC_CONTRACT.md.
// Not v1.0-frozen; see D-005/D-006 in decisions/OPEN_DECISIONS.md.
export const SLO = {
  P95_MS: 500,
  UNEXPECTED_ERROR_RATE: 0.01,
  CONTRACT_FAILURE_RATE: 0.01,
  SUCCESS_DELIVERY_RATE: 0.99,
};

const PROFILE = loadProfile();

export const BASE_URL = resolveBaseUrl(PROFILE);
export const API = `${BASE_URL}/api/v1`;
export const K6_IMAGE_DIGEST = resolveImageDigest(PROFILE);
export const REGION = PROFILE.region || fail('region is missing from profile');
export const ENVIRONMENT = PROFILE.environment || fail('environment is missing from profile');
export const SLO_VERSION = PROFILE.sloVersion || fail('sloVersion is missing from profile');
export const SEED_VERSION = PROFILE.seedVersion || fail('seedVersion is missing from profile');
export const REQUEST_MIX_VERSION = PROFILE.requestMixVersion
  || fail('requestMixVersion is missing from profile');
export const LIMITS = PROFILE.limits || fail('limits is missing from profile');
export const SCENARIOS = PROFILE.scenarios || fail('scenarios is missing from profile');
export const REQUEST_MIX = PROFILE.requestMix || fail('requestMix is missing from profile');

assertGoogleApiDisabled(PROFILE);

export function enforceRateLimit(rate) {
  if (rate > LIMITS.maxRate) {
    fail(`requested rate ${rate} exceeds profile limits.maxRate ${LIMITS.maxRate}`);
  }
  return rate;
}

export function enforceVuLimit(vus) {
  if (vus > LIMITS.maxVUs) {
    fail(`requested VUs ${vus} exceeds profile limits.maxVUs ${LIMITS.maxVUs}`);
  }
  return vus;
}

export function requireScenarioRate(scenarioName) {
  const scenario = SCENARIOS[scenarioName];
  if (!scenario) fail(`scenario "${scenarioName}" is not defined in profile.scenarios`);
  const rate = Number(__ENV.RATE) || scenario.rate;
  if (!rate) {
    fail(`scenario "${scenarioName}" has no rate; D-005 arrival-rate must be set via `
      + 'profile.scenarios.baseline.rate or the RATE env var before running this scenario');
  }
  return enforceRateLimit(rate);
}
