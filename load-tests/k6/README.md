# k6 Compose 예행 연습 (1일 Spike 확정 게이트)

세 문서를 코드로 옮긴 최소 스캐폴드입니다.

- `EXPERIMENT_SLO_PRE_REGISTRATION.md` → `load-tests/k6/config/thresholds.js` (draft SLO)
- `LOAD_TEST_SCENARIOS.md` → `flows/*.js`의 요청 모델 비중, `scenarios/*.js`의 Smoke/Normal 단계
- `K6_LOAD_TEST_TOOL_DECISION.md` 9~10장 → 디렉터리 구조, `summary.js`, `scripts/run-smoke.sh`

## 디렉터리 구조

```text
k6-load-test/
├── README.md
├── GATE_CHECKLIST.md          ← 10.2 확정 조건 체크리스트 (실행 순서 포함)
├── scripts/
│   └── run-smoke.sh           ← 1일 spike 실행 + evidence 저장
└── load-tests/k6/
    ├── lib/
    │   ├── config.js          ← BASE_URL, RUN_ID 등 env 주입
    │   ├── auth.js            ← VU별 토큰 발급·캐시
    │   └── data.js            ← 합성 계정/여행ID 로딩 (SharedArray)
    ├── flows/
    │   ├── plan-read.js       ← 조회 흐름 (요청 모델 초안 30%+15%+15%)
    │   └── timeline-write.js  ← 쓰기 흐름 (요청 모델 초안 15%+10%)
    ├── config/
    │   └── thresholds.js      ← SLO 초안 (동결 전, 안전선 용도)
    ├── scenarios/
    │   ├── smoke.js           ← 게이트용 최소 실행
    │   └── baseline.js        ← Normal 부하 (constant-arrival-rate)
    ├── data/
    │   ├── accounts.example.json
    │   └── travel-ids.example.json
    └── summary.js              ← summary.json / metadata.json 생성
```

## 실제 프로젝트에 붙이기 전에 확인할 것 (중요)

이 스캐폴드의 API 경로(`/api/travels`, `/api/travels/{id}/timeline-items`, `/api/auth/token/refresh` 등)는
이전에 공유해주신 PR diff(`lib/api/travel.ts`, `lib/api/timelineItems.ts`)에서 유추한 **추정치**입니다.
파일 안 `TODO` 주석을 실제 백엔드 스펙에 맞게 고쳐야 동작합니다. 특히:

1. **`lib/auth.js`의 토큰 발급 경로** — 실제 OAuth 로그인 화면 없이 테스트 계정의 access token을
   받을 수 있는 백엔드 엔드포인트가 있어야 합니다. 없다면 부하 테스트보다 이걸 먼저 만들어야 해요.
2. **`flows/timeline-write.js`의 payload 필드명** — `category`, `visitOrder` 등 실제 DTO와 맞는지 확인.
3. **`data/*.json`의 실제 값** — 테스트 계정 refresh token과 시드 여행 UUID를 채워야 합니다.

## 실행 순서

1. `load-tests/k6/data/accounts.example.json` → `accounts.json`으로 복사 후 실제 값 채우기
2. `load-tests/k6/data/travel-ids.example.json` → `travel-ids.json`으로 복사 후 실제 값 채우기
3. `.gitignore`에 `load-tests/k6/data/accounts.json`과 `load-tests/k6/data/travel-ids.json` 추가
4. `chmod +x scripts/run-smoke.sh`
5. production-like Compose 기동 확인
6. `BASE_URL=http://localhost:8080 ./scripts/run-smoke.sh` 실행
7. `evidence/load-tests/<run-id>/`에 생긴 `summary.json`, `metadata.json`, `raw.json`을
   `GATE_CHECKLIST.md`의 확정 조건과 하나씩 대조

## Normal(constant-arrival-rate) 실행 예시

```bash
docker run --rm --network host \
  -e BASE_URL=http://localhost:8080 \
  -e TARGET_RPS=5 \
  -e DURATION=10m \
  -v "$(pwd)/load-tests/k6:/scripts" -w /scripts \
  grafana/k6 run scenarios/baseline.js
```

`TARGET_RPS`는 아직 임의값입니다. AWS EC2 B-01에서 최대 안정 RPS를 찾기 전까지는
로컬 dry-run 용도로만 쓰고, 발표 자료의 SLO 근거로 사용하지 마세요.

## 다음에 채워 넣을 것 (아직 없음)

- `scenarios/ramp-spike-soak.js` — Ramp/Spike/Soak 단계 (B-01 포화점 탐색용)
- `scenarios/rollout-steady-load.js` — R-01~R-07 개입 구간용 고정 부하
- 운영 스크립트(`operations.jsonl` 기록용 AWS CLI/kubectl 래퍼) — k6 범위 밖이므로 별도 구현 필요
