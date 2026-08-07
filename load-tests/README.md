# Compose 부하·복구 원버튼 리허설

이 디렉터리는 production-like `compose.yml`을 대상으로 k6 요청, 합성 데이터,
Backend 재기동, T1~T6 회복 판정을 반복하는 로컬 검증 키트다.

이 리허설은 AWS의 ALB·ASG·RDS·관리형 Redis를 재현하지 않는다. 로컬 실행 결과는
스크립트·인증·데이터·증거 파이프라인이 동작하는지 확인하는 용도이며 AWS 성능 수치나
SLO 합격을 주장하는 근거가 아니다.

## 사전 조건

- Docker Desktop 또는 Docker Engine과 Compose v2
- 저장소 루트의 `.env.prod.example` 또는 사용자가 별도로 준비한 env 파일
- k6 이미지에 대한 Docker registry 접근
- 호스트 포트 `18080`을 사용할 수 있어야 한다. 필요하면 `--backend-port`로 변경한다.

실제 `.env.prod`나 `.env.dev`를 수정하거나 커밋하지 않는다. 기본값은 저장소의
`.env.prod.example`이며, 리허설은 고유한 Compose project와 임시 볼륨을 사용한다.

## 원버튼 실행

저장소 루트에서 실행한다.

```bash
./scripts/loadtest/run-compose-rehearsal.sh all \
  --env-file .env.prod.example \
  --users 20 \
  --rate 8
```

기본 `all` 순서는 다음과 같다.

1. 고유 Compose project로 Backend·PostgreSQL·Redis 기동
2. 사용자·Refresh Token·Travel·Timeline 합성 데이터 시드
3. Smoke
4. 새 데이터셋 재시드 후 Baseline
5. 새 데이터셋 재시드 후 16분 read-heavy steady load와 Refresh Token 회전
6. 8분 시점 Backend 재기동
7. 연속 2분 정상 창을 기준으로 T1→T6 판정
8. evidence 저장 후 해당 Compose project와 볼륨 정리

시간을 줄인 로컬 검증 예시는 다음과 같다.

```bash
BASELINE_DURATION=1m RECOVERY_DURATION=5m DRILL_AT_MIN=2 \
  ./scripts/loadtest/run-compose-rehearsal.sh all \
  --env-file .env.prod.example --users 2 --rate 1
```

개별 모드도 지원한다.

```bash
./scripts/loadtest/run-compose-rehearsal.sh smoke --users 2 --rate 1
./scripts/loadtest/run-compose-rehearsal.sh baseline --users 20 --rate 8
./scripts/loadtest/run-compose-rehearsal.sh recovery --users 20 --rate 8
```

진단을 위해 스택을 남길 때만 `--keep-stack`을 사용한다. 기본 project 이름이 아닌
프로젝트를 지정하려면 실수 방지를 위해 `ALLOW_NON_REHEARSAL_PROJECT=1`을 명시해야 한다.

## 인증과 합성 데이터

`seed-compose-load-data.py`는 백엔드의 현재 구현 계약을 소비한다.

- `user_table`에 합성 사용자를 추가한다.
- Redis에 `auth:refresh:token:<sha256>`와 `auth:refresh:family:<familyId>`를 만든다.
- 실제 `/api/v1/auth/token/refresh`를 한 번 호출해 회전 Cookie를 검증한다.
- 사용자별 Travel 하나와 `visitOrder` 1~3인 Timeline 세 개를 생성한다.
- `load-tests/k6/data/data.json`에 최소 credential만 0600으로 기록한다.

Refresh Token은 매번 회전되므로 각 단계는 새 데이터를 시드한다. `--tokens-only`는
읽기 전용 Smoke를 다시 실행할 때만 사용한다.

```bash
python3 scripts/loadtest/seed-compose-load-data.py \
  --env-file .env.prod.example \
  --project-name travel-planner-rehearsal-example \
  --base-url http://127.0.0.1:18080 \
  --tokens-only
```

실제 Token, Cookie, 개인 정보와 생성된 `evidence/`는 Git에 포함하지 않는다.

## 증거 구조

각 실행은 `evidence/load-tests/<run-id>/` 아래에 다음을 남긴다.

- `metadata.json`: Commit SHA, Compose project, k6 digest, rate, seed version
- `summary.json`: p95/p99, 오류율, contract failure, 성공 요청 수, dropped iterations
- `raw.json`: k6 Point 원본
- `k6-native-summary.json`: k6 native summary
- `operations.jsonl`: UTC 기준 RUN_START, T1, T2, T5, RUN_END
- `verdict.json`: 정상 기준 RPS, capacity floor, T1→T6 회복시간

복구 판정의 `T6`는 p95·예상하지 않은 오류율·contract failure·성공 처리용량을
연속 2분 만족한 시각이다. 로컬 Compose 재기동은 AWS B-02의 대응 실험일 뿐이며,
ASG 대체나 ALB 동작을 증명하지 않는다.

Baseline은 읽기와 Timeline 쓰기를 함께 검증하고, Recovery는 재기동 중 부분적으로
처리된 쓰기가 다음 순서 요청과 충돌하지 않도록 읽기·인증 회전 중심으로 구성한다.
이는 쓰기 기능을 제외한다는 뜻이 아니라, 장애 복구 시간창의 판정 변수를 줄이기 위한
리허설 전용 workload 선택이다.

## 검증 명령

```bash
bash -n scripts/loadtest/*.sh
python3 -m unittest discover -s load-tests/tests -p 'test_*.py'
docker compose --env-file .env.prod.example -f compose.yml config --quiet
```

PR 전에는 전체 Backend 테스트와 동일 조건 3회 리허설 결과를 함께 기록한다.
