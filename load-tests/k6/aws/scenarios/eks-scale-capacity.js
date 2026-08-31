// EKS monolith breakpoint scenario.
//
// This is one adaptive breakpoint stage. The controller launches it once per
// target rate (256, then exactly 2R) and stops only on an observed terminal;
// the k6 process itself never calls Kubernetes or AWS control-plane APIs.
import { runMixedCurrentOperation } from '../flows/current-feature-operations.js';
import { b01SpikeThresholds } from '../thresholds.js';
import { makeAwsSummaryHandler } from '../summary.js';
import { PROFILE_VERSION, SCENARIOS, enforceRateLimit, enforceVuLimit, requestMixFor } from '../config.js';

const STRESS = SCENARIOS['capacity-stress'];
if (!STRESS) throw new Error('[aws/eks-scale-capacity] profile.scenarios.capacity-stress is missing');
const RATE = Number(__ENV.CAPACITY_TARGET_RATE || __ENV.CONFIRMED_RATE || __ENV.RATE || STRESS.startRate);
if (!Number.isFinite(RATE) || RATE <= 0) {
  throw new Error('[aws/eks-scale-capacity] target rate must be a positive rate');
}

const CAMPAIGN_STAGE = __ENV.CAPACITY_STAGE || 'capacity-stress';
const ADAPTIVE = STRESS.adaptive === true
  || PROFILE_VERSION === 'aws-eks-monolith-breakpoint-v2.0'
  || PROFILE_VERSION === 'aws-eks-monolith-breakpoint-v2.1';
const REGISTERED_MULTIPLIERS = STRESS.stageMultipliers || [];
const REGISTERED_DURATIONS = STRESS.stageDurations || [];
let MULTIPLIERS = REGISTERED_MULTIPLIERS;
let DURATIONS = REGISTERED_DURATIONS;
let STAGE_RATES;
let STAGE_DURATION;
if (ADAPTIVE) {
  const target = Number(__ENV.CAPACITY_TARGET_RATE || __ENV.CONFIRMED_RATE || __ENV.RATE);
  if (!Number.isFinite(target) || target <= 0) {
    throw new Error('[aws/eks-scale-capacity] CAPACITY_TARGET_RATE must be a positive finite rate');
  }
  STAGE_RATES = [enforceRateLimit(target)];
  STAGE_DURATION = __ENV.CAPACITY_STAGE_DURATION || STRESS.duration || '5m';
  if (!/^[1-9][0-9]*[smh]$/.test(STAGE_DURATION)) {
    throw new Error('[aws/eks-scale-capacity] CAPACITY_STAGE_DURATION must be a whole-unit duration');
  }
  MULTIPLIERS = [1];
  DURATIONS = [STAGE_DURATION];
} else {
  MULTIPLIERS = CAMPAIGN_STAGE === 'pod-scale-out'
    ? REGISTERED_MULTIPLIERS.slice(0, 2)
    : CAMPAIGN_STAGE === 'recovery'
      ? [1]
      : REGISTERED_MULTIPLIERS;
  DURATIONS = CAMPAIGN_STAGE === 'pod-scale-out'
    ? REGISTERED_DURATIONS.slice(0, 2)
    : CAMPAIGN_STAGE === 'recovery'
      ? ['2m']
      : REGISTERED_DURATIONS;
  if ((CAMPAIGN_STAGE === 'capacity-stress' || CAMPAIGN_STAGE === 'node-scale-out-breakpoint')
      && (MULTIPLIERS.length < 5 || MULTIPLIERS[0] !== 1)) {
    throw new Error('[aws/eks-scale-capacity] breakpoint needs at least five stages starting at 1x');
  }
  if (CAMPAIGN_STAGE === 'pod-scale-out' && (MULTIPLIERS.length !== 2 || MULTIPLIERS[0] !== 1)) {
    throw new Error('[aws/eks-scale-capacity] pod scale-out needs registered 1x and 2x stages');
  }
  if (CAMPAIGN_STAGE === 'recovery' && MULTIPLIERS.length !== 1) {
    throw new Error('[aws/eks-scale-capacity] recovery must return to the 1x workload');
  }
  for (let index = 1; index < MULTIPLIERS.length; index += 1) {
    if (MULTIPLIERS[index] !== MULTIPLIERS[index - 1] * 2) {
      throw new Error('[aws/eks-scale-capacity] stageMultipliers must double monotonically');
    }
  }
  if (DURATIONS.length !== MULTIPLIERS.length) {
    throw new Error('[aws/eks-scale-capacity] stageDurations must match stageMultipliers');
  }
  STAGE_RATES = MULTIPLIERS.map((multiplier) => enforceRateLimit(RATE * Number(multiplier)));
}
const PRE_ALLOCATED_VUS = enforceVuLimit(Number(__ENV.PREALLOCATED_VUS || STRESS.preAllocatedVUs));
const MAX_VUS = enforceVuLimit(Number(__ENV.MAX_VUS || STRESS.maxVUs));
const MIX = requestMixFor('normal');

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    eksScaleCapacity: ADAPTIVE
      ? {
        executor: 'constant-arrival-rate',
        rate: STAGE_RATES[0],
        timeUnit: STRESS.timeUnit || '1s',
        duration: STAGE_DURATION,
        preAllocatedVUs: PRE_ALLOCATED_VUS,
        maxVUs: MAX_VUS,
        exec: 'mix',
        tags: {
          phase: CAMPAIGN_STAGE,
          platform: 'eks',
          adaptive: 'true',
          targetRate: String(STAGE_RATES[0]),
          stageIndex: String(__ENV.CAPACITY_STAGE_INDEX || 0),
        },
      }
      : {
        executor: STRESS.executor || 'ramping-arrival-rate',
        startRate: STAGE_RATES[0],
        timeUnit: STRESS.timeUnit || '1s',
        preAllocatedVUs: PRE_ALLOCATED_VUS,
        maxVUs: MAX_VUS,
        stages: STAGE_RATES.map((target, index) => ({ target, duration: DURATIONS[index] })),
        exec: 'mix',
        tags: { phase: CAMPAIGN_STAGE, platform: 'eks' },
      },
  },
  // Thresholds remain diagnostic. The coordinator/evaluator owns complete
  // 60-second SLO windows and terminal classification.
  thresholds: b01SpikeThresholds,
};

export function mix() {
  runMixedCurrentOperation(MIX);
}

export const handleSummary = makeAwsSummaryHandler('aws-eks-monolith-breakpoint');
