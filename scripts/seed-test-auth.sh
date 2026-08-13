#!/usr/bin/env bash
set -euo pipefail

# k6 부하 테스트용 계정을 Postgres(user_table)와 Redis(auth:refresh:*)에
# 실제 로그인 없이 직접 심는다. RedisRefreshTokenStore.save()가 만드는 것과
# 동일한 키 구조를 재현한다 (auth/repository/RefreshTokenStore.kt 참고).
# 각 계정 소유의 planner(여행)도 하나씩 만들어 travel-ids.json에 기록한다.

ACCOUNT_COUNT="${1:-2}"
TTL_MS=$((30 * 24 * 60 * 60 * 1000)) # 30일 — 테스트 중 만료 안 되게 넉넉히

: "${POSTGRES_USER:?.env의 POSTGRES_USER를 export 하세요}"
: "${POSTGRES_DB:?.env의 POSTGRES_DB를 export 하세요}"
: "${REDIS_PASSWORD:?.env의 REDIS_PASSWORD를 export 하세요}"

ACCOUNTS_FILE="load-tests/k6/data/accounts.json"
TRAVEL_IDS_FILE="load-tests/k6/data/travel-ids.json"
mkdir -p "$(dirname "$ACCOUNTS_FILE")"
echo "[" > "$ACCOUNTS_FILE"
echo "[" > "$TRAVEL_IDS_FILE"

for i in $(seq 1 "$ACCOUNT_COUNT"); do
  USER_ID="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT gen_random_uuid();" | tr -d '[:space:]')"
  PROVIDER_USER_ID="k6-load-test-${i}-$(date +%s)"
  NICKNAME="k6tester${i}-$(date +%s)"
  REFRESH_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
  FAMILY_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
  TOKEN_HASH="$(printf '%s' "$REFRESH_TOKEN" | shasum -a 256 | awk '{print $1}')"
  TRAVEL_ID="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT gen_random_uuid();" | tr -d '[:space:]')"

  docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    INSERT INTO user_table (id, provider, provider_user_id, email, name, nickname, profile_completed, created_at, updated_at)
    VALUES ('${USER_ID}', 'GOOGLE', '${PROVIDER_USER_ID}', 'k6-test-${i}-$(date +%s)@example.com', 'k6 테스트 계정 ${i}', '${NICKNAME}', true, now(), now());
  "

  docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    INSERT INTO planners_table (id, owner_id, title, start_date, end_date, country_id, city_id, companion_type, companion_count, version, created_at, updated_at)
    VALUES ('${TRAVEL_ID}', '${USER_ID}', 'k6 부하테스트용 여행 ${i}', CURRENT_DATE, CURRENT_DATE + 3, 1, 10, 'SOLO', 1, 0, now(), now());
  "

  docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning \
    SET "auth:refresh:token:${TOKEN_HASH}" "${USER_ID}|${FAMILY_ID}" PX "$TTL_MS" > /dev/null
  docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning \
    SET "auth:refresh:family:${FAMILY_ID}" "${TOKEN_HASH}" PX "$TTL_MS" > /dev/null

  SEP=$([ "$i" -lt "$ACCOUNT_COUNT" ] && echo "," || echo "")
  echo "  { \"refreshToken\": \"${REFRESH_TOKEN}\" }${SEP}" >> "$ACCOUNTS_FILE"
  echo "  \"${TRAVEL_ID}\"${SEP}" >> "$TRAVEL_IDS_FILE"
  echo "계정 ${i} 생성 완료 — userId=${USER_ID}, travelId=${TRAVEL_ID}"
done

echo "]" >> "$ACCOUNTS_FILE"
echo "]" >> "$TRAVEL_IDS_FILE"
echo "완료: ${ACCOUNTS_FILE}, ${TRAVEL_IDS_FILE}에 ${ACCOUNT_COUNT}개 테스트 계정/여행 저장됨"
