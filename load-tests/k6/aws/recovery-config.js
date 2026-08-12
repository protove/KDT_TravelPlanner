// Recovery-only profile loader. It deliberately does not import config.js,
// because config.js is coupled to the B-01 profile and its smoke/ramp/
// baseline/spike scenarios.

function fail(message) {
  throw new Error(`[aws/recovery-config] ${message}`);
}

function loadProfile() {
  const profilePath = __ENV.AWS_RECOVERY_PROFILE_FILE || '../../aws/profiles/ec2-recovery.json';
  let raw;
  try {
    raw = open(profilePath);
  } catch (error) {
    fail(`profile file not found: ${profilePath}`);
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    fail(`profile file is not valid JSON: ${profilePath}`);
  }
}

const LOADED_PROFILE = loadProfile();
const TARGET = LOADED_PROFILE.target || fail('target is missing');
const RECOVERY = LOADED_PROFILE.recovery || fail('recovery is missing');
const LIMITS = LOADED_PROFILE.limits || fail('limits is missing');

const baseUrl = __ENV.BASE_URL;
if (!baseUrl) fail('BASE_URL is required');
if (__ENV.ALLOW_INSECURE_TARGET !== '1' && !/^https:\/\//.test(baseUrl)) {
  fail(`BASE_URL must be HTTPS: ${baseUrl}`);
}
if (!/^https?:\/\/[^/]+$/.test(baseUrl) || /REPLACE_/.test(baseUrl)) {
  fail(`BASE_URL must be an approved http(s) origin: ${baseUrl}`);
}
if (TARGET.baseUrl && !/REPLACE_/.test(TARGET.baseUrl) && TARGET.baseUrl !== baseUrl) {
  fail(`BASE_URL does not match profile target.baseUrl: ${baseUrl}`);
}

const image = __ENV.K6_IMAGE_DIGEST || LOADED_PROFILE.k6Image;
if (!image || /REPLACE_/.test(image) || !/@sha256:[0-9a-f]{64}$/.test(image)) {
  fail('K6_IMAGE_DIGEST must be a digest-pinned image');
}
if (LOADED_PROFILE.googleApi && LOADED_PROFILE.googleApi.enabled) fail('googleApi.enabled must be false');

function positiveNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) fail(`${label} must be positive`);
  return number;
}

export const BASE_URL = baseUrl;
export const API = `${BASE_URL}/api/v1`;
export const K6_IMAGE_DIGEST = image;
export const ENVIRONMENT = LOADED_PROFILE.environment || fail('environment is missing');
export const REGION = LOADED_PROFILE.region || fail('region is missing');
export const SLO_VERSION = LOADED_PROFILE.sloVersion || fail('sloVersion is missing');
export const SEED_VERSION = LOADED_PROFILE.seedVersion || fail('seedVersion is missing');
export const REQUEST_MIX_VERSION = LOADED_PROFILE.requestMixVersion || fail('requestMixVersion is missing');
export const REQUEST_MIX = LOADED_PROFILE.requestMix?.steady || fail('requestMix.steady is missing');

const rate = positiveNumber(__ENV.RATE || RECOVERY.rate, 'RATE (D-005 frozen arrival rate)');
const maxRate = positiveNumber(LIMITS.maxRate, 'limits.maxRate');
if (rate > maxRate) fail(`RATE ${rate} exceeds limits.maxRate ${maxRate}`);
export const RATE = rate;
export const RECOVERY_OPTIONS = {
  executor: RECOVERY.executor || 'constant-arrival-rate',
  timeUnit: RECOVERY.timeUnit || '1s',
  duration: __ENV.DURATION || RECOVERY.duration || '20m',
  warmup: __ENV.WARMUP || RECOVERY.warmup || '3m',
  preAllocatedVUs: positiveNumber(__ENV.PREALLOCATED_VUS || RECOVERY.preAllocatedVUs, 'preAllocatedVUs'),
  maxVUs: positiveNumber(__ENV.MAX_VUS || RECOVERY.maxVUs, 'maxVUs'),
};
if (RECOVERY_OPTIONS.maxVUs > positiveNumber(LIMITS.maxVUs, 'limits.maxVUs')) {
  fail(`maxVUs ${RECOVERY_OPTIONS.maxVUs} exceeds limits.maxVUs ${LIMITS.maxVUs}`);
}

export const PROFILE = LOADED_PROFILE;
