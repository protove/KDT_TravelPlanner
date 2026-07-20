# KDT Travel Diary

Next.js 프런트엔드, Spring Boot Kotlin 백엔드, PostgreSQL, Redis를 Docker Compose로 실행하는 개발 환경입니다. `compose.yml`은 production-like 기본 구성이고, `compose.dev.yml`은 개발용 소스 마운트와 캐시 설정만 추가합니다.

## 구성

| 서비스 | 기술 | 호스트 접근 | Compose 내부 주소 |
| --- | --- | --- | --- |
| frontend | Next.js 16.2, React 19, TypeScript, Tailwind CSS 4 | `localhost:3000` | `frontend:3000` |
| backend | Spring Boot 3.5, Kotlin, JDK 21 | `localhost:8080` | `backend:8080` |
| backend management | Spring Boot Actuator, Prometheus | dev `localhost:9091`, prod-like 비공개 | `backend:9091` |
| postgres | PostgreSQL 17 | 공개하지 않음 | `postgres:5432` |
| redis | Redis 7.4 | 공개하지 않음 | `redis:6379` |

PostgreSQL과 Redis는 같은 Compose 네트워크의 backend에서만 접근할 수 있습니다. dev와 prod는 각각 `travel-diary-dev`, `travel-diary-prod`라는 `COMPOSE_PROJECT_NAME`을 사용하므로 컨테이너, 네트워크, 데이터 볼륨이 분리됩니다.

## 사전 준비

- Docker Desktop 또는 Docker Engine
- Docker Compose v2 이상

Node.js, JDK, Gradle은 호스트에 설치하지 않아도 됩니다. 모든 빌드와 실행은 컨테이너 내부에서 수행됩니다.

## 환경변수 준비

실제 환경 파일은 Git에서 제외됩니다. 저장소를 처음 받은 경우 예제 파일을 복사합니다.

```bash
cp .env.dev.example .env.dev
cp .env.prod.example .env.prod
```

예제에 포함된 비밀번호는 로컬 전용입니다. 실제 배포에서는 비밀 저장소를 통해 주입해야 합니다.

`NEXT_PUBLIC_API_BASE_URL`은 브라우저 번들에 포함되므로 runner 이미지 빌드 시점에 고정됩니다. `INTERNAL_API_BASE_URL`은 Next.js 서버가 Compose 네트워크 안에서 backend를 호출할 때 사용하는 런타임 값입니다.

## 개발 환경 실행

```bash
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml up --build
```

- 프런트엔드: <http://localhost:3000>
- 백엔드 ping: <http://localhost:8080/api/ping>
- 백엔드 health: <http://localhost:9091/actuator/health>
- 백엔드 Prometheus metrics: <http://localhost:9091/actuator/prometheus>

`frontend/` 변경은 Next.js Fast Refresh로 반영됩니다. `backend/src/` 변경은 Gradle 연속 컴파일 후 Spring Boot DevTools가 애플리케이션 컨텍스트를 재시작합니다. `build.gradle.kts`나 `settings.gradle.kts`를 변경한 경우에는 이미지를 다시 빌드하세요.

```bash
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml up --build backend
```

호스트에서 `3000`, `8080`, `9091` 포트를 이미 사용 중이라면 `.env.dev`의 `FRONTEND_PORT`, `BACKEND_PORT`, `MANAGEMENT_PORT`, `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOWED_ORIGINS`를 함께 확인하세요. 컨테이너 간 주소인 `INTERNAL_API_BASE_URL=http://backend:8080`과 관리 포트 `backend:9091`은 그대로 유지합니다.

백엔드는 소셜 로그인 후 발급하는 서비스 Access Token을 서명하기 위해 `JWT_SECRET`을 사용합니다. `.env.dev`와 `.env.prod`에는 32바이트 이상의 임의 값을 설정해야 하며, Grafana 관리자 비밀번호와는 별도의 값을 사용하세요.

## Monitoring 수집 스택 실행

Prometheus, Loki, Alloy, Grafana는 기본 애플리케이션 실행에 포함되지 않는 옵트인 오버레이입니다. Alloy는 Docker 소켓 없이 `backend_logs` 볼륨을 읽기 전용으로 마운트해 현재 백엔드 로그 파일을 Loki로 전달합니다.

실행 전 `.env.dev`와 `.env.prod`에 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`를 설정해야 합니다. 비밀번호가 없으면 모니터링 오버레이는 시작되지 않으며 익명 접근과 사용자 임의 가입은 비활성화됩니다.

```bash
# dev: 관리·수집 포트를 localhost에 공개
docker compose --env-file .env.dev \
  -f compose.yml \
  -f compose.dev.yml \
  -f compose.monitoring.yml \
  -f compose.monitoring.dev.yml \
  up --build -d --wait

# prod-like: Prometheus, Loki, Alloy는 Compose 내부망에서만 접근
docker compose --env-file .env.prod \
  -f compose.yml \
  -f compose.monitoring.yml \
  up --build -d --wait
```

dev에서는 다음 주소로 수집 상태를 확인할 수 있습니다.

- Prometheus: <http://localhost:9090>
- Loki readiness: <http://localhost:3100/ready>
- Alloy UI: <http://localhost:12345>
- Grafana: <http://localhost:3001>

Grafana에는 UID가 고정된 Prometheus·Loki 데이터소스와 `TravelPlanner/Backend Overview` 대시보드가 자동 프로비저닝됩니다. Prometheus, Loki, Grafana 데이터와 Alloy 수집 위치는 named volume에 저장됩니다. 기본 보관 기간은 dev 7일, prod-like 30일이며 `down`만 실행하면 데이터가 유지됩니다.

```bash
./monitoring/validate-configs.sh

# dev 종료
docker compose --env-file .env.dev \
  -f compose.yml \
  -f compose.dev.yml \
  -f compose.monitoring.yml \
  -f compose.monitoring.dev.yml \
  down

# prod-like 종료
docker compose --env-file .env.prod \
  -f compose.yml \
  -f compose.monitoring.yml \
  down
```

## 컨테이너 내부 접속

실행 중인 컨테이너의 셸에 접속할 때는 `<service>`를 `frontend`, `backend`, `postgres`, `redis` 중 하나로 바꿉니다. Alpine 기반 이미지이므로 `bash` 대신 `sh`를 사용합니다.

```bash
# dev 환경
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml \
  exec <service> sh

# prod-like 환경
docker compose --env-file .env.prod \
  exec <service> sh
```

예를 들어 dev backend와 prod PostgreSQL에 접속하는 명령은 다음과 같습니다.

```bash
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml \
  exec backend sh

docker compose --env-file .env.prod \
  exec postgres sh
```

`exec`는 해당 서비스가 실행 중일 때만 사용할 수 있습니다. production runner의 frontend와 backend는 비루트 사용자로 실행되며, 디버깅 도구가 최소한으로만 포함되어 있습니다.

## Production 이미지 검증

dev 환경을 종료한 다음 `.env.prod`로 runner 이미지를 빌드합니다.

```bash
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml down
docker compose --env-file .env.prod build
```

빌드한 이미지와 PostgreSQL·Redis 연결까지 smoke test하려면 다음과 같이 실행합니다.

```bash
docker compose --env-file .env.prod up -d --wait
curl --fail http://localhost:8080/api/ping
curl --fail http://localhost:3000/
docker compose --env-file .env.prod \
  exec -T backend wget -q -O /dev/null http://127.0.0.1:9091/actuator/health
docker compose --env-file .env.prod down
```

이 구성의 PostgreSQL과 Redis는 실제 RDS나 관리형 Redis가 아니라 로컬 runner 이미지 검증용 컨테이너입니다. 실제 배포에서는 접속 정보를 RDS·관리형 Redis 값으로 교체하고 인프라 컨테이너를 배포 대상에서 제외합니다.

## 종료와 데이터 영속성

일반적인 종료에는 `down`을 사용합니다. 컨테이너와 네트워크는 제거되지만 named volume과 데이터는 유지됩니다.

```bash
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml down
docker compose --env-file .env.prod down
```

환경별 실제 볼륨은 `COMPOSE_PROJECT_NAME` 접두어로 분리됩니다.

- `travel-diary-dev_postgres_data`, `travel-diary-dev_redis_data`
- `travel-diary-prod_postgres_data`, `travel-diary-prod_redis_data`

데이터를 포함해 해당 환경을 완전히 초기화할 때만 `down -v`를 사용합니다. 다음 명령으로 삭제한 데이터는 복구할 수 없습니다.

```bash
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml down -v
docker compose --env-file .env.prod down -v
```

`docker volume prune`도 사용하지 않는 named volume을 삭제할 수 있으므로 실행 전에 대상 볼륨을 확인해야 합니다.

## PostgreSQL 백업과 복원

named volume 자체는 백업이 아닙니다. PostgreSQL 데이터는 raw 데이터 디렉터리를 복사하지 않고 `pg_dump`와 `psql`을 사용합니다.

```bash
# dev 백업
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml \
  exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > travel-diary-dev.sql

# dev 복원
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml \
  exec -T postgres sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  < travel-diary-dev.sql
```

## 개별 검증

```bash
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml config
docker compose --env-file .env.prod config

docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml \
  run --rm --no-deps frontend npm run lint
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml \
  run --rm --no-deps backend ./gradlew test --no-daemon
```

## 향후 운영 방향

- Nginx를 추가하면 Nginx만 호스트에 공개하고 `/`는 frontend, `/api`는 backend로 전달합니다.
- 실제 운영 DB는 RDS로 전환하고 자동 백업, 스냅샷, PITR을 사용합니다.
- CI에서는 실행마다 격리된 임시 볼륨을 사용하고 테스트 종료 후 제거합니다.
