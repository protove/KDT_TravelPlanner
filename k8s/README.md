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
├── metrics-server.yaml           kind 전용 패치 포함 (하단 HPA 섹션 참고)
├── hpa.yaml                      backend HorizontalPodAutoscaler
└── scripts/
    ├── setup.sh                  클러스터 생성 → 이미지 빌드/로드 → apply 전체 자동화
    ├── setup-hpa.sh               setup.sh 이후 추가로 실행하는 HPA 애드온 스크립트
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

## HPA 메커니즘 검증

**이건 메커니즘 검증이지 실제 규모/성능 테스트가 아니다.** 목적은 HPA 설정 문법과 실제 스케일 업/다운 동작을 EKS(유료) 대신 kind(무료)에서 먼저 확인하는 것이다. 검증된 `hpa.yaml`은 SCRUM-11(EKS 이전)에서 거의 그대로 옮기되, `metrics-server.yaml`은 EKS에서 애드온으로 재설치한다 — 이 파일의 kind 전용 인자(`--kubelet-insecure-tls` 등)는 EKS에는 필요 없다. CI(`k8s-verify.yml`)에는 포함하지 않는다(탐색적 작업, 매 PR 자동화 대상 아님).

`minReplicas: 2` / `maxReplicas: 4` / CPU 목표 60%는 임의로 정한 값이 아니라, 지금 dev EC2 ASG(`infra/environments/dev-runtime/main.tf`)의 `asg_min_size=2` / `asg_desired_capacity=2` / `asg_max_size=4` / `target_cpu_utilization=60`을 그대로 맞춘 것이다 — HPA로 넘어가도 스케일링 동작 범위가 지금 운영 중인 것과 동일하게 유지되도록.

### ASG ↔ HPA 메커니즘 대조표

EC2 ASG(`infra/modules/backend_service/main.tf`)와 최대한 같은 메커니즘으로 비교 가능하게 맞춘 결과다. min/max/desired 외의 항목도 전수 확인했다.

| 항목 | ASG (dev-runtime 실제값) | kind HPA/Deployment | 상태 |
|---|---|---|---|
| min / desired / max | 2 / 2 / 4 | `minReplicas: 2` / `replicas: 2` / `maxReplicas: 4` | 매칭 |
| 스케일링 지표 | CPU 60% (`ASGAverageCPUUtilization`, TargetTrackingScaling) | CPU 60% (`averageUtilization: 60`) | 매칭 |
| 헬스체크 대상 | ALB target group: `GET /actuator/health/readiness`, 포트 9091, HTTP, matcher 200 | `readinessProbe`: 동일 경로·포트 | 매칭 (1단계 PR부터 이미 동일) |
| 헬스체크 주기/임계치 | interval 15s, healthy_threshold 2, unhealthy_threshold 3, timeout 5s | periodSeconds 10, timeoutSeconds 5, failureThreshold 10 | **의도적으로 다름** — Flyway 마이그레이션이 최대 180초 걸릴 수 있어 readinessProbe를 더 관대하게 잡음. ALB 숫자에 맞추면(예: failureThreshold 3) 정상 기동 중에도 NotReady로 튕길 위험이 있어 그대로 둠. "같은 엔드포인트를 본다"는 정합성이 숫자 일치보다 중요하다고 판단 |
| 신규 인스턴스 워밍업 | `health_check_grace_period=300s`, `default_instance_warmup=180s` | 대응 필드 없음 | HPA 컨트롤러의 전역 옵션(`--horizontal-pod-autoscaler-cpu-initialization-period`, 기본 300s로 ASG와 동일)이 개념적으로 대응하지만, 개별 `HorizontalPodAutoscaler` 리소스가 아니라 `kube-controller-manager` 클러스터 전역 플래그라 `hpa.yaml`에서 조정 불가. EKS는 관리형 컨트롤 플레인이라 이 플래그 자체를 사용자가 바꿀 수 없음 — kind/EKS 둘 다 우리가 손댈 수 있는 영역이 아님 |

### 사용법

`setup.sh`로 기본 클러스터를 띄운 뒤, 추가로 실행한다:

```bash
./k8s/scripts/setup.sh
./k8s/scripts/setup-hpa.sh
```

`setup-hpa.sh`는 `metrics-server.yaml` → `hpa.yaml` 순서로 apply하고, metrics-server 첫 메트릭 수집(최대 1분 정도 걸리는 알려진 지연)까지 대기한다.

### 관찰

```bash
kubectl top pods -n travel-planner        # <unknown>이면 metrics-server 문제
kubectl get hpa -n travel-planner -w      # TARGETS/REPLICAS 실시간 관찰
```

### 부하 생성

클러스터 안에서 backend Service를 직접 때리는 임시 Pod를 여러 개 띄운다 (host→port-forward 경유보다 안정적이고 CPU 부하도 더 잘 준다):

```bash
kubectl run load-gen-1 --image=busybox --restart=Never -n travel-planner -- \
  /bin/sh -c "while true; do wget -q -O- http://backend:8080/api/ping; done"
kubectl run load-gen-2 --image=busybox --restart=Never -n travel-planner -- \
  /bin/sh -c "while true; do wget -q -O- http://backend:8080/api/ping; done"
```

CPU 사용률이 60% 이상으로 올라가면 `kubectl get hpa -n travel-planner -w`에서 REPLICAS가 2→3→4로 늘어나는 걸 몇 분 안에 볼 수 있다.

### 부하 Pod 정리

```bash
kubectl delete pod load-gen-1 load-gen-2 -n travel-planner
```

정리 후 기본 down-scale stabilization window(5분)가 지나면 REPLICAS가 다시 `minReplicas`(2)로 줄어든다.

## Rolling Update / 자가치유 검증

**이것도 메커니즘 검증이지 실제 이미지 교체 시나리오는 아니다.** AWS와 무관한 순수 쿠버네티스 메커니즘이라 kind에서 완전히 검증 가능하고, 새 인프라가 필요 없어 HPA보다 가볍다. HPA(PR #367)로 `replicas: 2`가 이미 적용되어 있어서 여러 Pod 상황을 자연스럽게 다룰 수 있다. `backend-deployment.yaml`에 `strategy`(`maxSurge: 1`, `maxUnavailable: 0`)를 명시적으로 고정해, 복제본 수가 바뀌어도 항상 무중단이 보장되도록 했다 — `maxUnavailable: 0`은 "기존 Pod는 새 Pod가 Ready 될 때까지 절대 안 내림"이라는 뜻이다. CI(`k8s-verify.yml`)에는 포함하지 않는다(HPA와 마찬가지로 탐색적 검증, 매 PR 자동화 대상 아님). 새 이미지 빌드/배포 시나리오도 다루지 않는다 — 실제 이미지 교체는 CI가 이미 매 PR마다 `setup.sh`로 하고 있어 `rollout restart`로 메커니즘만 확인하면 충분하다.

**`strategy`만으로는 실제로 무중단이 아니었다 — `lifecycle.preStop`이 추가로 필요했다.** 처음 `strategy`만 넣고 검증했을 때 `rollout-probe`에 `FAIL`이 2건(connection refused, download timed out) 나왔다. 원인은 레이스 컨디션이다: Pod가 삭제되면 (1) 컨테이너에 SIGTERM이 가고 (2) Service 엔드포인트 목록에서 빠지는 것(kube-proxy 반영)이 동시에 시작되는데, 이 둘은 서로 순서 보장이 없다. 이 프로젝트 백엔드는 `server.shutdown: graceful`(`application.yml`)이 켜져 있어 SIGTERM을 받자마자 새 연결을 거부하기 시작하는데, 그 시점에 아직 일부 노드의 kube-proxy가 이 Pod를 엔드포인트에서 못 뺐다면 그쪽으로 라우팅된 요청이 실패한다. `maxUnavailable: 0`은 "새 Pod가 Ready 되기 전엔 기존 Pod 개수를 안 줄인다"만 보장할 뿐, 종료 중인 Pod로 향하는 개별 요청의 성공을 보장하지 않는다. 해결: `preStop` 훅으로 SIGTERM 전에 짧게 sleep을 둬서, 엔드포인트 목록이 갱신될 시간을 벌어준다:
```yaml
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep 5"]
```
이 훅을 추가한 뒤 동일한 `rollout-probe` 검증을 다시 돌리자 `FAIL` 0건이 됐다.

### 사용법

`setup.sh`로 기본 클러스터를 띄운 뒤(`strategy`/`preStop` 필드가 반영된 채로), Rolling Update는 새 이미지 빌드 없이 `rollout restart`로 메커니즘만 검증한다. 무중단인지 증명하려면 재시작 도중 계속 요청을 보내면서 실패가 없는지 봐야 한다 — in-cluster에서 반복 요청을 걸어두는 Pod를 하나 띄우고, 그 동안 `rollout restart`를 실행한다:

```bash
# 터미널 1: 재시작 도중 계속 요청 (in-cluster, port-forward보다 안정적)
kubectl run rollout-probe --image=busybox --restart=Never -n travel-planner -- \
  /bin/sh -c "while true; do wget -q -O- -T 2 http://backend:9091/actuator/health/readiness || echo FAIL; sleep 0.5; done"

# 터미널 2: 롤링 재시작 실행 + 관찰
kubectl rollout restart deployment/backend -n travel-planner
kubectl rollout status deployment/backend -n travel-planner
```

자가치유는 Pod를 강제로 지우고 Deployment가 다시 살리는지 확인한다:

```bash
kubectl get pods -n travel-planner -l app=backend   # Pod 이름 확인
kubectl delete pod <backend-pod-이름> -n travel-planner
kubectl get pods -n travel-planner -l app=backend -w   # 즉시 새 Pod가 만들어지는지 관찰
```

### 관찰

```bash
kubectl logs rollout-probe -n travel-planner   # FAIL 없어야 무중단 확인 완료
kubectl get pods -n travel-planner -l app=backend   # 자가치유 후 새 Pod가 Running/READY 1/1, replicas: 2 유지
```

### 결과

`strategy` + `preStop` 반영 후 재검증 결과: Rolling Update 도중 `rollout-probe` 로그에 `FAIL` 0건 — 무중단 확인 완료. Pod 삭제 후 새 Pod(`backend-8cf6d475f-h9wzv`)가 9초 만에 생성되어 `Running`/`READY 1/1`이 됐고 `replicas: 2`가 그대로 유지됨 — 자가치유 확인 완료.

### 검증용 리소스 정리

```bash
kubectl delete pod rollout-probe -n travel-planner
```

### 추가 검증: HPA `maxReplicas`에 다 찬 상태에서 Rolling Update

**`maxReplicas`는 HPA 전용 상한선이라 Rolling Update의 surge를 막지 않는다.** `strategy.maxSurge: 1`은 "그 순간의 `spec.replicas`보다 최대 1개 더 만들 수 있다"는 뜻이지 "HPA의 `maxReplicas`를 넘으면 안 된다"는 뜻이 아니다 — 그래서 HPA가 이미 `replicas`를 4(max)로 올려둔 상태에서 배포해도 순간적으로 5대까지 올라갔다가 4대로 내려오는 걸 반복하며 무중단을 유지할 수 있는지 확인했다.

EC2 ASG와 대조되는 지점이기도 하다: `asg_max_size`는 ASG 자체의 하드 캡이라, desired_capacity가 이미 max_size에 찬 상태에서 Instance Refresh를 돌리면 surge용 여유 자리가 없어 헌 인스턴스를 먼저 종료해야 하는 경우가 생긴다(AWS 공식 문서에 명시된 제약) — 그 순간 목표 용량 미달이 발생할 수 있다. k8s는 `maxReplicas`가 Deployment의 surge를 제한하지 않으므로 이 문제가 구조적으로 없다.

#### 사용법

`setup.sh` → `setup-hpa.sh`로 HPA를 켠 뒤, HPA 검증과 같은 방식으로 부하를 걸어 `replicas`를 4(max)까지 올린다:

```bash
kubectl run load-gen-1 --image=busybox --restart=Never -n travel-planner -- \
  /bin/sh -c "while true; do wget -q -O- http://backend:8080/api/ping; done"
kubectl run load-gen-2 --image=busybox --restart=Never -n travel-planner -- \
  /bin/sh -c "while true; do wget -q -O- http://backend:8080/api/ping; done"
kubectl run load-gen-3 --image=busybox --restart=Never -n travel-planner -- \
  /bin/sh -c "while true; do wget -q -O- http://backend:8080/api/ping; done"

kubectl get hpa backend -n travel-planner -w   # REPLICAS가 4가 될 때까지 대기
```

4대 모두 `Running`/`READY 1/1`이 된 뒤, 부하가 걸린 채로(load-gen 유지) `rollout-probe`를 띄우고 롤링 재시작:

```bash
kubectl run rollout-probe --image=busybox --restart=Never -n travel-planner -- \
  /bin/sh -c "while true; do wget -q -O- -T 2 http://backend:9091/actuator/health/readiness || echo FAIL; sleep 0.5; done"

kubectl rollout restart deployment/backend -n travel-planner
kubectl rollout status deployment/backend -n travel-planner
```

#### 관찰

```bash
kubectl logs rollout-probe -n travel-planner   # FAIL 없어야 무중단 확인 완료
kubectl get pods -n travel-planner -l app=backend   # 롤아웃 도중 4→5(surge)→4 반복 관찰
```

#### 결과

CPU 사용률 153%(목표 60% 대비 과부하 유지)인 상태에서도 Pod 개수가 4 → 5(surge) → 4를 반복했고, **Ready 상태 Pod는 전체 과정에서 한 번도 4 밑으로 떨어지지 않았다.** `rollout-probe` 로그 `FAIL` 0건 — HPA가 상한까지 찬 상태에서도 `strategy` + `preStop` 조합이 무중단을 유지함을 확인. (Pod 목록이 순간적으로 6개까지 보이는 경우가 있었는데, 이는 실제 초과가 아니라 `preStop`의 5초 유예 동안 `Terminating` 상태로 남아있는 헌 Pod와 다음 surge Pod가 겹쳐 `kubectl get pods` 목록에 동시에 잡힌 것 — 트래픽은 받지 않는다.)

#### 검증용 리소스 정리

```bash
kubectl delete pod load-gen-1 load-gen-2 load-gen-3 rollout-probe -n travel-planner
```

## 다음 단계로 넘어가는 조건

이 단계가 안정적으로 재현 가능해야 한다 — `setup.sh` → `teardown.sh` → `setup.sh`를 몇 번 반복해도 매번 성공해야 frontend 컨테이너화(2단계)로 넘어간다. 한 번 됐다고 바로 다음 단계로 가지 않는다.
