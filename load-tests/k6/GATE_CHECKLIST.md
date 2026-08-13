# 1일 Spike 확정 게이트 체크리스트

> 출처: `K6_LOAD_TEST_TOOL_DECISION.md` 10.2. 여기서 하나라도 실패하면
> k6를 바로 폐기하지 말고, 인증·데이터·runner 병목부터 분리해 진단할 것.

## 실행 전 준비

- [ ] `load-tests/k6/data/accounts.example.json` → `accounts.json`으로 복사 후 실제 테스트 계정 refresh token 채움
- [ ] `load-tests/k6/data/travel-ids.example.json` → `travel-ids.json`으로 복사 후 실제 시드 여행 UUID 채움
- [ ] `.gitignore`에 `load-tests/k6/data/accounts.json`, `load-tests/k6/data/travel-ids.json` 추가 (토큰 커밋 금지)
- [ ] `lib/auth.js`, `flows/plan-read.js`, `flows/timeline-write.js`의 `TODO` 경로를 실제 백엔드 스펙에 맞게 수정
- [ ] production-like Compose가 떠 있고 `/api/travels` 등에 로컬에서 접근 가능한지 확인

## 실행

```bash
chmod +x scripts/run-smoke.sh
BASE_URL=http://localhost:8080 ./scripts/run-smoke.sh
```

## 확정 조건 (10.2)

- [ ] 동일 조건 3회 실행이 재현 가능하다 (`run-smoke.sh`를 세 번 연속 돌려서 확인).
- [ ] 합성 계정과 토큰 준비가 수동 복사 없이 수행된다 (스크립트/시드 절차로 자동화).
- [ ] p95/p99·오류율·RPS·`dropped_iterations`가 `summary.json`에 남는다.
- [ ] 요청명(`name` tag)의 cardinality가 통제된다 (동적 UUID를 그대로 tag로 쓰지 않았는지 확인).
- [ ] 결과에 credential·Cookie·개인정보가 포함되지 않는다 (`summary.json`, `metadata.json`, `raw.json` 육안 확인).
- [ ] k6 runner의 CPU·Memory·Network가 병목이 아니다 (`docker stats`로 실행 중 관찰).
- [ ] threshold 실패가 non-zero exit code로 전달된다 (`echo $?`로 확인).
- [ ] 실행과 정리 절차를 팀원이 이 README/체크리스트만 보고 반복할 수 있다.

## 통과 후 다음 단계

- [ ] `scenarios/baseline.js`로 `constant-arrival-rate` Normal 부하 실행 (`TARGET_RPS`, `DURATION` env로 조정)
- [ ] AWS EC2 B-01로 넘어가기 전, `config/thresholds.js`의 draft 값이 로컬 환경에서도
      합리적인지 재확인 (단, 최종 동결은 EC2 B-01 이후에만 한다 — SLO 문서 4장 참고)
