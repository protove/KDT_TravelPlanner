import { SharedArray } from 'k6/data';

// 합성 계정·여행 데이터는 이 파일에서 "어떻게 불러오는지"만 정의하고,
// 실제 값은 data/accounts.json, data/travel-ids.json에 둔다 (git에는 커밋하지 않음 — .gitignore 참고).
// SharedArray를 쓰면 모든 VU가 같은 배열을 메모리에 한 번만 올려 공유한다.
//
// 실행 전 준비물 (K6_LOAD_TEST_TOOL_DECISION.md 8.2 데이터 원칙):
//   - data/accounts.json: [{ "refreshToken": "..." },...] 사전 발급된 테스트 계정
//   - data/travel-ids.json: ["uuid1", "uuid2", ...] 시드로 미리 생성해둔 여행 ID
//   - accounts.json과 travel-ids.json은 scripts/seed-test-auth.sh가 같은 순서로
//     함께 생성한다 — 즉 accounts[i]의 소유 여행이 travelIds[i]다. 두 함수는
//     반드시 같은 vuId 기준(vuId % length)으로 골라야 계정-여행 소유권이 맞는다.

export const accounts = new SharedArray('test accounts', function () {
  return JSON.parse(open('../data/accounts.json'));
});

export const travelIds = new SharedArray('seed travel ids', function () {
  return JSON.parse(open('../data/travel-ids.json'));
});

// VU마다 고정된 계정을 배정한다 — 같은 실행 안에서 계정이 바뀌지 않아야
// 토큰 캐시(lib/auth.js)가 제대로 재사용된다.
export function pickAccount(vuId) {
  return accounts[vuId % accounts.length];
}

// accounts와 동일한 vuId 기준으로 골라야 VU가 자신이 소유한 travelId만 사용한다.
// (accounts[i] owner == travelIds[i]의 소유자, seed-test-auth.sh 참고)
export function pickTravelId(vuId, iter) {
  return travelIds[vuId % travelIds.length];
}
