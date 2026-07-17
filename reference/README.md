# KDT-TravelPlanner Codex 문서 묶음

이 폴더는 Notion의 기능 요구서, API 명세서, 메뉴 구조도와 최신 ERD를 Codex가 참고하기 쉬운 Markdown 형식으로 정리한 결과물이다.

## 파일

- `CODEX_CONTEXT.md`: Codex가 먼저 읽을 프로젝트 규칙과 문서 우선순위
- `CONVENTION.md`: 백엔드 이름, 패키지, DTO, 데이터베이스 식별자 컨벤션
- `FUNCTIONAL_REQUIREMENTS.md`: 기능 범위, 권한, 확정·계획 상태
- `API_SPEC.md`: 현재 API 엔드포인트와 요청 규칙
- `MENU_STRUCTURE.md`: 화면과 메뉴 계층, 권한, API 연결
- `ERD.md`: 최신 ERD의 테이블, 관계, 제약조건, 미정 사항
- `GIT_STRATEGY.md`: 브랜치와 PR 운영 전략
- `spring-boot-logging-security-policy.md`: Spring Boot 로그 수집과 보안 정책
- `monitoring-privacy-logging-plan.md`: 개인정보 보호 로깅 팀 토의안
- `monitoring-privacy-logging-plan.png`: 팀 토의안 16:9 요약 이미지
- `monitoring-privacy-logging-plan.svg`: 요약 이미지 편집 원본
- `docker-ci-verification-strategy.md`: Docker 이미지·실행 설정과 PR별 CI 검증 전략
- `docker-ci-verification-strategy.png`: Docker 기반 CI 전략 16:9 요약 이미지
- `docker-ci-verification-strategy.svg`: CI 전략 이미지 편집 원본

## 저장 위치 권장

프로젝트 저장소에서 다음과 같이 배치할 수 있다.

```text
docs/
├── CODEX_CONTEXT.md
├── FUNCTIONAL_REQUIREMENTS.md
├── API_SPEC.md
├── MENU_STRUCTURE.md
└── ERD.md
```

Codex 작업 요청 예시:

```text
docs/CODEX_CONTEXT.md와 관련 문서를 먼저 읽고,
현재 API 및 ERD에 맞춰 여행 플랜 초대 기능을 구현해줘.
문서에서 TBD로 표시된 구조는 임의로 확정하지 말고 질문해줘.
```
