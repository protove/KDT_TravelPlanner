# Compose 부하·복구 원버튼 리허설

이 디렉터리는 production-like `compose.yml`을 대상으로 k6 요청, 합성 데이터,
Backend 장애·복구, T1~T6 회복 판정을 반복하는 로컬 검증 키트다.

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
6. 8분 시점 Backend `stop-start` 드릴
7. T1(중단 요청)·T2(중단 확인)·T4(복구 시작)·T5(healthy)를 기록
8. 연속 2분 정상 창을 기준으로 T4→T6 및 T1→T6 판정
9. evidence 저장 후 해당 Compose project와 볼륨 정리

복구 실행은 `RECOVERY_DURATION >= DRILL_AT_MIN * 60 + 180초`를 시작 전에
검증한다. 드릴 후 최소 3분 관측이 확보되지 않으면 Compose를 기동하지 않고
실패한다. Gate 판정에는 `stop-start`만 사용한다. `restart`는 T1과 T4가 한
명령에 붙어 측정 분리가 되지 않으므로 진단용으로만 허용한다.

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
./scripts/loadtest/run-compose-rehearsal.sh spike --users 20 --rate 8 \
  --spike-peak-rate 24 --spike-hold 1m
```

## Compose Gate 반복 실행

`load-tests/gate-profile.json`의 조건을 고정해 baseline·recovery를 3회 연속
실행하고, 마지막에 짧은 3배 Spike를 실행한다. 각 Cycle은 고유 Compose project와
Run ID를 사용한다.

```bash
python3 scripts/loadtest/run-compose-gate.py \
  --profile load-tests/gate-profile.json \
  --env-file .env.prod.example

python3 scripts/loadtest/summarize-gate.py \
  evidence/load-tests/<gate-id>-gate-manifest.json \
  --data-file load-tests/k6/data/data.json
```

Gate는 실행 조건, threshold, T4/T6, dropped iterations, k6 runner 통계와
credential·Cookie·합성 개인정보 검사를 함께 판정한다. Gate가 통과하기 전에는
k6 도구 채택을 확정하지 않으며, 통과 후에도 `SLO_VERSION`은 AWS B-01 전까지
동결하지 않는다. 2026-08-07 실행 결과는
`evidence/load-tests/gate-report.json`에서 `passed=true`로 확인한다.

2026-08-07 고정 profile 결과는 다음과 같다.

| cycle | baseline requests / p95 / p99 | recovery T4→T6 | dropped iterations |
|---:|---|---:|---:|
| 1 | 6,257 / 21.408ms / 35.753ms | 166.8s | 0 |
| 2 | 6,261 / 21.996ms / 39.962ms | 131.0s | 0 |
| 3 | 6,259 / 23.388ms / 40.375ms | 128.1s | 0 |

Spike(8→24→8, peak hold 1분)는 2,774 requests, p95 13.838ms, p99 21.634ms,
`dropped_iterations=0`이었다. Gate 결과는 Compose 계측·반복성 증거이며 AWS
성능/SLO 합격 선언이 아니다.

## 관측 스택 리허설

기존 monitoring overlay를 함께 올리면 Prometheus·Loki·Alloy·Grafana가 같은
Compose project에 연결된다. Compose 파일은 변경하지 않고 `--with-monitoring`으로
overlay만 추가한다.

```bash
./scripts/loadtest/run-compose-rehearsal.sh recovery \
  --with-monitoring --env-file .env.prod.example \
  --drill-mode stop-start --rate 8

python3 scripts/loadtest/publish-grafana-annotations.py \
  evidence/load-tests/<run-id>-recovery-recovery-steady \
  --user "$GRAFANA_ADMIN_USER" \
  --password "$GRAFANA_ADMIN_PASSWORD"
```

Annotation에는 Run ID, scenario와 T0~T6 event만 기록하며 token·Cookie를 넣지
않는다. Grafana 화면만 보존하지 말고 `operations.jsonl`, annotation export,
PromQL/LogQL 결과와 k6 원본을 같은 UTC 시간 범위로 보존한다.

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
- `operations.jsonl`: UTC 기준 RUN_START, T0, T1, T2, T3(관측 시), T4, T5, T6, RUN_END
- `runner-stats.jsonl`: k6 Docker runner CPU·Memory·Network 샘플
- `evidence-safety.json`: credential·Cookie·합성 개인정보 검사 결과
- `verdict.json`: 정상 기준 RPS, capacity floor, T1→T6 및 T4→T6 회복시간
- `<gate-id>-gate-manifest.json`·`gate-report.json`: 고정 조건 반복과 Gate 판정

복구 판정의 `T6`는 p95·예상하지 않은 오류율·contract failure·성공 처리용량을
연속 2분 만족한 시각이다. 로컬 Compose stop-start는 AWS B-02의 대응 실험일 뿐이며,
ASG 대체나 ALB 동작을 증명하지 않는다.

Baseline은 읽기와 Timeline 쓰기를 함께 검증하고, Recovery는 재기동 중 부분적으로
처리된 쓰기가 다음 순서 요청과 충돌하지 않도록 읽기·인증 회전 중심으로 구성한다.
이는 쓰기 기능을 제외한다는 뜻이 아니라, 장애 복구 시간창의 판정 변수를 줄이기 위한
리허설 전용 workload 선택이다.

### AWS B-01 phase fixture

AWS B-01은 Smoke·Ramp·Baseline·Spike 각 phase 시작 전에 같은 Run ID의 synthetic
planner만 exact Run ID 경계로 삭제하고 FK cascade로 timeline을 정리한 뒤, 사용자별 planner 1개와
timeline 3개를 다시 seed한다. `seed-aws-load-data.py`는 DB count를 확인한 뒤에만
`seedState=complete`를 기록한다. 검증 결과는 credentials 파일과 별도의
`evidence/aws-load-tests/<run-id>/fixtures/<phase>.json`에 저장하며, 이 파일에는
자격증명이나 사용자 ID를 넣지 않는다. fixture 검증이 실패하면 해당 k6 phase는
실행되지 않고 `seedState=in-progress`로 남는다.

각 phase stage marker는 fixture ID, `fixtures/<phase>.json` 상대 경로와 기대 user 수를
함께 기록한다. 최종 `validate-aws-run.py`는 Smoke·Ramp·Baseline 3회·Spike의 marker와
fixture를 모두 확인하고, users/planners/timeline이 `N/N/3N`, planner당 timeline이
정확히 3인지 검증한다. 하나라도 누락·교환·불일치하면 `gate-report.json`의
`fixtures.passed=false`가 되고 최종 `passed`도 false가 된다.

## 검증 명령

```bash
bash -n scripts/loadtest/*.sh
python3 -m unittest discover -s load-tests/tests -p 'test_*.py'
docker compose --env-file .env.prod.example -f compose.yml config --quiet
```

PR 전에는 전체 Backend 테스트, 동일 조건 3회 리허설, Spike 1회와 보안 검사 결과를
함께 기록한다. 이 문서의 SLO 값은 Compose 측정 가능성 확인용 초안이며 AWS B-01
이전에는 `v1.0-frozen`으로 바꾸지 않는다.
