# MSA 서비스 경계 설계 (초안)

## 1. 문제 상황

현재 backend는 하나의 Gradle 모듈, 하나의 Spring 애플리케이션으로 동작하는 모놀리식 구조다. 도메인별 패키지(`auth`, `user`, `community`, `travel`, `membership`, `location`, `place`, `route`, `timeline`)는 분리돼 있지만, 실제 MSA로 전환할 경우 어느 경계로 서비스를 나눠야 할지는 아직 정해지지 않았다.

kind 환경에서 PDB/HPA 검증, ArgoCD 도입까지 진행되면서 인프라 쪽은 GitOps로 관리 가능한 상태가 되어가고 있다. 다음 단계로 "실제 MSA 전환은 언제, 어떻게 할 것인가"를 검토하되, **전환 시점은 아직 확정되지 않았으므로 지금은 코드를 변경하지 않고 설계만 남겨둔다.**

## 2. MSA 분리 기준

DDD(Domain-Driven Design)의 Bounded Context 개념을 적용해 도메인 경계를 나누되, 무조건 잘게 쪼개지 않는다. 트랜잭션이 자주 얽히거나 결합도가 높은 도메인은 하나의 서비스로 묶어서 운영하는 전략을 택했다. 이 프로젝트는 트래픽 특성보다는 **도메인 간 실제 코드 결합도**(JPA 엔티티 직접 참조, 같은 트랜잭션에서 여러 Repository 사용 여부)를 1차 기준으로 삼았다.

## 3. 실제 프로젝트의 서비스 분리 후보

### (1) Identity 서비스 — `auth`, `user`

- **분리 이유**: 인증/권한 관리는 다른 도메인과 직접적인 연관이 적고, 서비스 전체의 공통 레이어로 동작해야 한다. `auth` 패키지는 OAuth(Google/Naver), 토큰, 로그인/로그아웃 로직이 이미 별도로 모여 있어 구조적으로 독립적이다.
- **설계 방향**: JWT(HS256, 공유 시크릿) 기반 인증은 서비스가 분리돼도 시그니처 검증 자체는 독립적으로 가능하다. **다만 지금 `JwtAuthenticationFilter`가 매 요청마다 `userRepository.existsById()`로 DB 조회를 한다(검증됨)** — 분리 시 이 체크를 버릴지, User 서비스를 호출할지 결정이 필요하다. 후보 중 가장 먼저 분리하기 좋은 서비스로 판단된다.

### (2) Travel 서비스 — `travel`, `membership`, `timeline`, `route`, `place`

- **분리 이유**: `TravelMember`("누가 이 여행에 참여하고 어떤 권한을 갖는가")는 User보다 여행이라는 컨텍스트에 종속적이라 Travel에 포함시켰다(미검증). Route는 이미 Adapter/Port 구조(`GoogleRoutesAdapter`, `RouteCalculationPort`)가 있어 외부 연동은 잘 분리돼 있지만, 이게 "독립 서비스로 빼야 한다"는 뜻은 아니다. Place도 `TravelMapPointService`가 `TravelRepository`/`TravelMemberRepository`/`TimelineItemRepository`를 함께 쓴다고 알려져 있어(미검증) 사실상 Travel 기능의 일부에 가깝다.
- **설계 방향**: `Travel` 엔티티가 `User`/`Country`/`City`를 ID가 아니라 JPA 엔티티로 직접 참조하고, `TravelUpdateService` 하나가 `TravelRepository`/`TravelMemberRepository`/`CountryRepository`/`CityRepository`/`TimelineItemRepository`/`PlannerPurposeRepository` 6개를 한 트랜잭션에서 쓴다고 알려져 있다(**전부 미검증 — 실제 분리 착수 전 코드로 재확인 필요**). 사실이면 MSA 전환 시 가장 먼저 손봐야 할 지점이다.

### (3) Location 서비스 — `location`

- **분리 이유**: `Country`/`City` 데이터는 상대적으로 정적이고 다른 도메인에서 참조만 하는 구조로 보인다(미검증).
- **설계 방향**: Travel/Timeline이 `countryId`/`cityId`로 조회할 때, 데이터가 정적이므로 캐싱을 우선 검토하고 매 요청마다 동기 호출하지 않는 방향을 고려한다.

### (4) Community 서비스 — `community` (게시글 + 댓글)

- **분리 이유**: 게시글과 댓글 자체는 트래픽·결합도 면에서 하나로 묶는 게 맞다(FK 양방향 CASCADE, 스케일링 이유 차이 없음 — 별도 조사로 검증됨). 다만 Identity/Travel과는 명확한 결합 지점이 있어 별도 서비스 후보로 분리했다.
- **설계 방향** (모두 검증됨 — 직접 코드 확인):
  - `CommunityPost`/`CommunityComment`가 `User`를 단순 FK가 아니라 JPA `@ManyToOne`으로 직접 참조. 목록 조회 쿼리도 `post.author.nickname` 등을 JOIN으로 직접 읽음 → 분리 시 로컬 스냅샷 캐시 또는 User 서비스 동기 호출 필요.
  - `CommunityPostService.verifySourceTravelReadAccess`가 `TravelRepository`/`TravelMemberRepository`를 인프로세스로 직접 호출 → 분리 시 API 호출로 전환 필요. Community 도메인에서 발견된 결합 중 가장 큼.
  - DB FK: `community_*` 테이블 전부 `user_table` FK(`CASCADE`), `community_post`는 `planners_table`(travel) FK(`SET NULL`)도 보유 → 분리 시 DB 레벨 FK 제거, 애플리케이션 레벨 정합성으로 대체 필요.

## 4. 결론

### (1) 적용한 MSA 분리 원칙

- DDD Bounded Context로 도메인을 나누되, 트랜잭션/결합이 강한 도메인(Travel↔Membership↔Timeline↔Route↔Place)은 하나의 서비스로 묶었다.
- 코드로 실제 검증된 결합(Community)과 아직 검증 안 된 결합(Travel 계열)을 구분해서 기록했다 — 미검증 항목은 실제 분리 착수 전 재확인이 필요하다.
- DB 소유권과 통신 방식은 지금 확정하지 않고, 원칙만 아래에 남긴다.

**DB 소유권 원칙(초안)**

| 서비스 | 소유 데이터(안) |
|---|---|
| Identity | `user_table`, 인증/토큰 관련 테이블 |
| Travel | `planners_table`, `travel_member`, `timeline_item`, `planner_purpose` 등 |
| Location | `country`, `city` |
| Community | `community_post`, `community_comment`, `community_tag`, `community_reaction`, `community_comment_reaction` |

다른 서비스는 원칙적으로 소유 서비스의 DB를 직접 조회하지 않고 API로만 접근한다.

**통신 방식 원칙**: 처음에는 REST로 충분하다. Kafka/RabbitMQ 같은 이벤트 브로커는 실제로 필요해지는 시점(비동기 정합성 요구 등)에 도입을 검토하고 지금 미리 넣지 않는다.

### (2) 예상되는 효과

서비스별 독립 배포/스케일링이 가능해지고, Identity처럼 결합도 낮은 도메인부터 점진적으로 분리하면 리스크를 줄일 수 있다. 문서화만 해두면 실제 전환 시점에 결합 지점을 다시 조사하지 않아도 된다.

### (3) 향후 개선 방향 (지금 하지 않는 것)

- Entity/Repository 분리, Port/Adapter 인터페이스 도입, 서비스 간 REST Client 구현, DB 실제 분리, 이벤트 브로커 도입, 실제 서비스 추출 — 전부 지금은 하지 않는다. 실제 전환 시점이 정해지면 그때 진행한다.
- Travel 계열의 미검증 항목(Travel→User/Country/City 직접 참조, TravelUpdateService 다중 Repository 의존, Timeline→Travel/City, Membership→Travel/User)은 실제 분리 작업 착수 전 코드로 재확인이 필요하다.
- 백로그에 EKS+ArgoCD vs MSA+ArgoCD 부하테스트 비교로 보이는 티켓(SCRUM-30~33)이 있다 — 이 문서가 해당 작업의 MSA 설계 입력으로 재사용될 수 있는지 팀과 확인이 필요하다.
