# kind 로컬 클러스터 (EKS 이전 1단계)

이 디렉터리는 backend를 로컬 [kind](https://kind.sigs.k8s.io/)(Kubernetes-in-Docker) 클러스터에 올려서, 실제 k8s Deployment/Service로 운영했을 때 어떻게 동작하는지 프로덕션을 건드리지 않고 검증하기 위한 것이다. 자세한 배경은 [이슈 #331](https://github.com/protove/KDT_TravelPlanner/issues/331) 참고.

## 지금 여기서 하는 것과 하지 않는 것

- **한다**: backend + Postgres + Redis를 kind에 올려서 Deployment/Service/probe/ConfigMap/Secret이 제대로 동작하는지 로컬에서 확인
- **하지 않는다**:
  - frontend는 포함하지 않는다. 프로덕션에서도 컨테이너로 안 돌고 Next.js 정적 export로 S3+CloudFront에 배포된다. `frontend/Dockerfile`의 `runner` 스테이지는 standalone 빌드를 가정하는데 `next.config.ts`는 `output: "export"`라 실제로 컨테이너 빌드가 깨지는 상태 — 별도 이슈에서 다룬다.
  - CI(GitHub Actions) 연동은 이번 범위 밖이다. 로컬 실행 전용.
  - Ingress도 이번 범위 밖이다. `kubectl port-forward`로 충분하다.

## 프로덕션 인프라와의 관계

**이 안의 Postgres/Redis는 로컬 전용 스탠드인이다.** 프로덕션은 RDS(PostgreSQL)와 ElastiCache(Redis)를 쓰고(`infra/modules/backend_data`), 실제 EKS 이전 시에도 이 둘은 그대로 유지될 가능성이 높다. 이 매니페스트가 그대로 프로덕션에 올라가는 게 아니다.

## 디렉터리 구조

```text
k8s/
├── kind-config.yaml              kind 클러스터 설정 (단일 control-plane 노드)
├── namespace.yaml                travel-planner 네임스페이스
├── postgres-deployment.yaml      postgres:17.10-alpine (compose.yml과 동일 버전)
├── postgres-service.yaml
├── postgres-pvc.yaml
├── redis-deployment.yaml         redis:7.4.9-alpine, --requirepass
├── redis-service.yaml
├── redis-pvc.yaml
├── backend-configmap.yaml        비-민감 환경변수
├── backend-secret.example.yaml   실제 값 없는 키 목록 (문서 목적)
├── backend-deployment.yaml       backend Dockerfile의 runner 타겟 이미지, probe 포함
├── backend-service.yaml          ClusterIP, 8080(app) + 9091(actuator)
└── scripts/
    ├── setup.sh                  클러스터 생성 → 이미지 빌드/로드 → apply 전체 자동화
    └── teardown.sh               kind delete cluster
```

## 사용법

레포 루트에 `.env.dev`가 있어야 한다 (`.env.dev.example` 참고, `compose.dev.yml` 로컬 개발과 동일 파일).

```bash
./k8s/scripts/setup.sh
```

내부적으로 순서대로 실행된다:

1. `kind create cluster --config kind-config.yaml` (이미 있으면 건너뜀)
2. `docker build --target runner`로 backend 이미지 빌드 (`travel-planner-backend:kind-local`)
3. `kind load docker-image`로 이미지를 클러스터 노드에 로드
4. `namespace.yaml` apply
5. `kubectl create secret generic backend-secret --from-env-file=.env.dev` (재실행해도 최신 값으로 갱신됨)
6. postgres/redis PVC+Deployment+Service apply, Ready까지 대기
7. backend ConfigMap+Deployment+Service apply, Ready까지 대기 (Flyway 마이그레이션 포함 최대 180초)

### 확인

```bash
kubectl config current-context                 # kind-travel-planner-local
kubectl get pods -n travel-planner              # postgres/redis/backend 전부 Running, READY 1/1
kubectl port-forward svc/backend 9091:9091 -n travel-planner &
curl localhost:9091/actuator/health/readiness   # {"status":"UP"}
```

`logback-spring.xml`이 `dev` 프로파일에서 root 레벨을 `WARN`으로 설정해두어 Flyway의 INFO 로그는 `kubectl logs`에 나타나지 않는다 (앱 설계상 의도된 동작, k8s 이슈 아님). 마이그레이션 성공 여부는 대신 DB에서 직접 확인한다:

```bash
kubectl exec deploy/postgres -n travel-planner -- \
  psql -U travel_diary_dev -d travel_diary_dev \
  -c "SELECT version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
```

### 정리

```bash
./k8s/scripts/teardown.sh
docker ps                        # kind 관련 컨테이너 안 남아있는지 확인
kubectl config get-contexts      # kind-travel-planner-local context 제거 확인
```

## 핵심 설계 결정

- **backend 이미지는 `runner`(프로덕션) 타겟으로 빌드한다.** hot-reload용 `dev` 타겟이 아니다 — 목적이 "실제 배포 이미지가 k8s에서 어떻게 동작하는가" 검증이기 때문.
- **probe는 `compose.yml`의 healthcheck를 그대로 옮겼다.** readiness → `GET :9091/actuator/health/readiness`, liveness → `GET :9091/actuator/health/liveness`. management 포트(9091)가 앱 포트(8080)와 분리되어 있다.
- **환경변수는 ConfigMap(비민감)/Secret(민감)으로 분리한다.** `postgres`, `redis`처럼 k8s Service DNS 이름을 그대로 호스트명으로 쓴다. `PROFILE_IMAGE_STORAGE_ENABLED=false`로 둬서 로컬에서 S3 의존성을 끊는다.
- **`LOGGING_FILE_NAME`을 명시적으로 오버라이드한다.** `application-dev.yml`의 기본 로그 경로는 `/app` 기준 상대경로(`logs/travel-planner.log`)라 `runner` 이미지(`spring` 유저, `/app`은 root 소유)에서는 쓸 수 없어 기동이 실패한다. `compose.dev.yml`이 로컬 개발에서 쓰는 것과 동일하게 Dockerfile이 이미 `spring` 소유로 만들어둔 `/var/log/travel-planner/travel-planner.log`로 고정한다.
- **Secret은 레포에 실값으로 커밋하지 않는다.** `.gitignore`에 이미 걸려있는 `.env.dev`에서 `--from-env-file`로 로컬에서만 생성한다. `backend-secret.example.yaml`은 어떤 키가 필요한지 보여주는 문서용 파일이며 값은 비어 있다.
- **`backend-secret` 하나를 postgres/redis/backend 세 워크로드가 공유한다.** Spring이 기대하는 환경변수 이름(`SPRING_DATASOURCE_USERNAME` 등)과 시크릿 키 이름(`POSTGRES_USER` 등)이 다르므로, backend Deployment는 `envFrom`이 아니라 개별 `env[].valueFrom.secretKeyRef`로 명시적으로 매핑한다. OAuth/Maps 키처럼 로컬에서 비어있을 수 있는 키는 `optional: true`로 선언한다.
- **Postgres/Redis는 Deployment+PVC(단일 replica)로 충분하다.** StatefulSet 같은 고가용성 구성은 쓰지 않는다 — 실제 HA는 RDS/ElastiCache가 담당하는 영역이라서다.
- **스토리지는 kind 기본 `local-path-provisioner` 그대로 쓴다.** host mount 안 함. `kind delete cluster`로 노드 컨테이너가 삭제되면 데이터도 함께 사라지는데, 이번 용도는 "매번 새로 검증하는 로컬 샌드박스"라 이 휘발성이 오히려 자연스럽다 (Flyway가 매 기동 시 스키마를 재구성한다).
- **이미지 로딩은 `kind load docker-image`만 쓴다.** 로컬 레지스트리는 안 쓴다 — backend 이미지 하나뿐이고 반복 재빌드가 잦은 단계가 아니다.
- **접속은 `kubectl port-forward`만 쓴다.** Ingress는 이번 범위에서 제외.
- **노드는 control-plane 단일 노드다.** 지금 검증 대상(env 설정, probe, DB/Redis 연결)은 노드가 여러 개인지와 무관하다.

## 다음 단계로 넘어가는 조건

이 단계가 안정적으로 재현 가능해야 한다 — `setup.sh` → `teardown.sh` → `setup.sh`를 몇 번 반복해도 매번 성공해야 frontend 컨테이너화(2단계)로 넘어간다. 한 번 됐다고 바로 다음 단계로 가지 않는다.
