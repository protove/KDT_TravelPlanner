# 모니터링 검증

이 디렉터리의 설정은 Prometheus, Loki, Alloy, Grafana 수집 경로를 구성한다. 관련 파일이 변경된 PR에서는 `Monitoring Verification` workflow가 정적 검사와 통합 스모크를 실행한다.

이 문장의 변경은 최초 도입된 workflow가 GitHub 러너에서 실행되는지 확인하기 위한 일회성 검증 표본이다.
추가 커밋은 열린 PR의 `synchronize` 이벤트를 확인한다.

## 로컬 실행

정적 설정 검증:

```bash
./monitoring/validate-configs.sh
```

배포용 `runner` 이미지와 prod-like 모니터링 구성 검증:

```bash
./monitoring/smoke-test.sh prod
```

개발용 backend 이미지와 dev 모니터링 구성 검증:

```bash
./monitoring/smoke-test.sh dev
```

스모크 테스트는 고유한 Compose 프로젝트와 임시 볼륨을 사용하고 종료 시 리소스를 정리한다. 실제 `.env` 파일이나 운영 비밀값은 사용하지 않는다.

## CI 합격 조건

- dev·prod Compose와 Prometheus·Loki·Alloy·Grafana 설정이 유효하다.
- backend, Prometheus, Loki, Alloy, Grafana가 기동한다.
- Prometheus의 backend·Prometheus·Loki·Alloy target이 모두 `UP`이다.
- 합성 HTTP 요청의 metric과 구조화 로그가 각각 Prometheus와 Loki에서 조회된다.
- Grafana datasource와 `Backend Overview` dashboard가 provisioning된다.
- prod-like 구성의 backend 관리 포트와 수집기 포트가 호스트에 공개되지 않는다.

모든 관련 PR은 prod-like 스모크를 실행한다. dev 전용 Compose·설정·backend 개발 이미지가 변경된 경우에만 dev 스모크를 추가해 로컬 개발 경로를 검증한다. 이 게이트는 이미지 배포나 실제 운영 환경 기동을 수행하지 않는다.
