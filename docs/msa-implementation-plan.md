# MSA 구현 계획 및 담당 배정

## 배경

`docs/msa-service-boundaries.md`(서비스 경계 설계 초안)를 바탕으로, 팀 회의에서 MSA를 실제로 구현하고 EKS+ArgoCD(모놀리스) vs MSA+ArgoCD 부하테스트 비교(SCRUM-30~33으로 추정)를 하기로 확정했다. **마감: 다음주 화요일까지 MSA 분리 완료.**

이 문서는 "PoC 스코프"를 전제로 한다 — 완벽한 프로덕션 MSA가 아니라, 부하테스트 비교에 필요한 만큼만 분리한다. 특히 **DB는 물리적으로 분리하지 않는다** (데이터 마이그레이션은 이번 스코프 밖, 다음 단계 과제).

## 전체 설계

### 서비스 경계 (4개, 확정)

| 서비스 | 포함 도메인 | 담당 |
|---|---|---|
| Identity | `auth`, `user` | 본인 |
| Community | `community` (게시글+댓글) | Community 담당자 |
| Travel | `travel`, `membership`, `timeline`, `route`, `place` | Travel 담당자 |
| Location | `location` | (별도 서비스로 안 뜯음, 스키마만 분리 — 아래 참고) |

Location은 이번 스코프에서 별도 서비스로 배포하지 않는다. 스키마만 분리해서 Travel이 Port를 통해 접근하는 구조까지만 준비한다(자세한 이유는 `docs/msa-service-boundaries.md` 참고).

### DB 전략: 스키마 분리 (멘토님 추천)

물리적으로 별도 DB 인스턴스를 만드는 대신, **하나의 Postgres 안에서 도메인별 스키마를 나누고 서비스별 계정에 자기 스키마만 권한(GRANT)을 준다.**

- 스키마: `identity`, `community`, `travel`, `location`
- 각 서비스는 자기 스키마만 접근 가능 (다른 스키마 접근 시 DB 권한 에러 — 실수 방지용 안전망)
- 예외 없음: Travel도 자기 스키마(`travel`)만 접근하고, User/Location 데이터는 반드시 API로 조회 (아래 통신 패턴 참고)

### 통신 패턴 (모든 서비스 쌍에 동일 적용)

기존 `route` 패키지가 이미 이 패턴을 쓰고 있다 (`route/port/RouteCalculationPort.kt` + `route/adapter/GoogleRoutesAdapter.kt`로 Google Routes API 호출) — 새 패턴이 아니라 기존 컨벤션을 내부 서비스 호출에도 그대로 적용하는 것.

1. **REST 동기 호출** (이벤트 브로커 안 씀)
2. **인증은 JWT 그대로 forward** — 호출하는 서비스가 원래 요청의 `Authorization` 헤더를 그대로 복사해서 전달. 새 인증 방식 안 만듦 (모든 서비스가 같은 `JWT_SECRET` 공유, HS256)
3. **서비스 디스커버리는 k8s Service DNS** — 예: `http://identity-service:8080`, `http://backend:8080`(Travel은 당분간 기존 backend 배포를 그대로 가리킴)
4. **설정은 기존 `app.external.*` 스타일을 `app.internal.*`로 재사용**:
   ```yaml
   app:
     internal:
       identity-service:
         base-url: http://identity-service:8080
         connect-timeout: 1s
         read-timeout: 2s
   ```
5. **타임아웃 + 실패 시 완화** — 호출 실패 시 예외로 전체를 죽이지 않고 `null` 반환 등으로 완화 (장애 격리 데모 취지에 맞게)

### Port/Adapter 컨벤션

각 서비스가 다른 도메인을 참조할 때, 인터페이스(Port)를 그 도메인이 필요한 패키지 안에 정의하고, 구현체(Adapter)는 지금은 기존 Repository를 감싸는 임시 버전으로 시작한다. 실제 서비스가 뜨면 어댑터만 HTTP 클라이언트로 교체 — 서비스 코드(비즈니스 로직)는 안 바뀐다.

```
{domain}/port/{Name}Port.kt       ← 인터페이스, 필요한 최소 데이터만 반환하는 DTO 포함
{domain}/adapter/Jpa{Name}Adapter.kt   ← 임시: 기존 Repository 직접 사용
{domain}/adapter/Http{Name}Adapter.kt  ← 최종: 실제 서비스 API 호출 (나중에 추가)
```

## 담당 배정

### 본인 — 사전작업 + Identity + ArgoCD

- [x] `community/port/UserLookupPort.kt`, `TravelAccessPort.kt` — 완료
- [x] `community/adapter/JpaUserLookupAdapter.kt`, `JpaTravelAccessAdapter.kt` — 완료
- [ ] `CommunityCommentService`/`CommunityPostService`/DTO들을 Port 쓰게 전환 — 진행 중
- [ ] Travel의 `GET /api/v1/travels/{travelId}/read-access` 엔드포인트 추가
- [ ] DB 스키마 4개 생성 + 테이블 이동 + 서비스별 계정/GRANT
- [ ] Identity 전용 서비스 구축 (auth+user 코드 이동, JWT 로직, `GET /api/v1/users/{id}/summary` API)
- [ ] ArgoCD kind 설치 + Application 매니페스트(backend/identity-service/community-service) + 검증
- [ ] API 계약 정리해서 공유 (아래 "다른 담당자를 위한 계약" 참고)

### Community 담당자

**참고할 기존 코드**: `community/port/UserLookupPort.kt`, `TravelAccessPort.kt`(이미 있음, 본인이 만들어둠), `community/adapter/Jpa*.kt`(임시 구현체, 이미 있음)

- [ ] Community 전용 Spring Boot 서비스 구축
- [ ] `community/adapter/JpaUserLookupAdapter.kt` → `HttpUserLookupAdapter.kt`로 교체 (Identity의 `GET /users/{id}/summary` 호출)
- [ ] `community/adapter/JpaTravelAccessAdapter.kt` → `HttpTravelAccessAdapter.kt`로 교체 (Travel의 `GET /travels/{id}/read-access` 호출)
- [ ] Dockerfile + k8s manifest (Deployment/Service/HPA/PDB — `k8s/backend-*.yaml` 패턴 참고)
- [ ] (여유되면) `CommunityComment.author: User` / `CommunityPost.author: User` 엔티티를 `authorId: UUID`로 완전 분리 (Flyway 마이그레이션 포함)

### Travel 담당자

**참고할 기존 코드**: `route/port/RouteCalculationPort.kt` + `route/adapter/GoogleRoutesAdapter.kt` (외부 API 호출 패턴, 그대로 재사용), `community/port/UserLookupPort.kt` (구조 참고)

- [ ] `travel/port/TravelUserPort.kt` — `Travel.owner: User` 참조 끊기 (`UserLookupPort`와 거의 동일한 인터페이스)
- [ ] `travel/port/TravelLocationPort.kt` — `Travel.country`/`Travel.city`, `TimelineItem.city` 참조 끊기
- [ ] `travel/adapter/JpaTravelUserAdapter.kt`, `JpaTravelLocationAdapter.kt` (임시 구현체)
- [ ] `TravelUpdateService`에서 `CountryRepository`/`CityRepository` 부분만 `TravelLocationPort`로 교체 — 나머지 4개 Repository(`TravelRepository`/`TravelMemberRepository`/`TimelineItemRepository`/`PlannerPurposeRepository`)는 전부 Travel 자기 도메인이라 안 건드림
- [ ] 나중에 Identity/Location 서비스 뜨면 HTTP 어댑터로 교체

### 부하테스트 담당자

- [ ] 시나리오 설계 (일반 부하 + 장애 격리 테스트 — Community 죽였을 때 Travel은 계속 동작하는지 등)
- [ ] k6 스크립트 작성
- [ ] EKS+ArgoCD(모놀리스) vs MSA+ArgoCD 결과 비교

### 발표 담당자

- [ ] 최종 발표자료, 시연영상
- [ ] 발표 시 명확히 할 것: 이번 PoC 범위(프로세스 분리+ArgoCD)와 의도적으로 뺀 것(DB 물리분리, Location 별도서비스)을 구분해서 설명

### 전체 공통

- [ ] 각자 본인 작업 트러블슈팅 내용을 진행하면서 기록 (나중에 문서화/Runbook에 취합)

## 다른 담당자를 위한 계약 (지금 확정된 API 스펙)

### Identity → `GET /api/v1/users/{userId}/summary`
```json
{ "id": "uuid", "nickname": "string", "profileImageUrl": "string | null" }
```
인증: `Authorization: Bearer <원래 요청자의 JWT>` 필요.

### Travel(당분간 backend) → `GET /api/v1/travels/{travelId}/read-access`
```json
true | false
```
인증: `Authorization: Bearer <원래 요청자의 JWT>` 필요. 404 대신 여행 없음/권한 없음 둘 다 `false` 반환 (필요시 구현 담당자가 세부 조정).

## 일정

| 일차 | 본인 | Community 담당 | Travel 담당 |
|---|---|---|---|
| Day 1(오늘) | Community Port 전환 마무리 + DB 스키마 설계 | Port 계약 보고 서비스 스캐폴딩 시작 | Port 계약 보고 서비스 스캐폴딩 시작 |
| Day 2~3 | Identity 서비스 구축 | Community 서비스 코드 이동 | Travel Port 작업 |
| Day 3~4 | ArgoCD kind 도입 | 임시 어댑터로 로컬 검증 | 임시 어댑터로 로컬 검증 |
| Day 4~5 | Identity API 완성 → 계약 공유 | 실제 HTTP 어댑터로 교체 | 실제 HTTP 어댑터로 교체 |
| Day 5~6 | 전체 통합 검증 (kind) | 통합 검증 참여 | 통합 검증 참여 |

## 스코프 밖 (의도적으로 안 함, 발표 시 명시)

- DB 물리 분리 (스키마 분리로 대체)
- Location 별도 서비스 배포
- Community 엔티티 완전 분리 (여유 시 스트레치 목표)
- 이벤트 기반 비동기 통신, gRPC
