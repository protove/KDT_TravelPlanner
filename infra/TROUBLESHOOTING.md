# Terraform 인프라 트러블슈팅

SCRUM-10(EKS 클러스터 신규 구축) 작업 중 겪은 문제와 해결 과정을 기록한다. 둘 다
코드 버그가 아니라 "로컬에서는 안 보이고 CI/보안 스캔에서만 드러나는" 종류의 문제라,
다음에 새 모듈/환경을 추가하는 사람이 같은 데 걸리지 않도록 남겨둔다.

## 1. CI에서 "missing or corrupted provider plugins"로 Validate/Test 실패

### 증상

새 모듈(`infra/modules/eks_cluster`)과 새 환경(`infra/environments/dev-eks`)을 추가하고
로컬에서 `terraform init -backend=false && terraform validate && terraform test`를 전부
통과시킨 뒤 PR을 올렸는데, GitHub Actions의 `Validate`/`Test` job만 이렇게 실패했다.

```text
Error: missing or corrupted provider plugins:
  - registry.terraform.io/hashicorp/aws: the cached package for registry.terraform.io/hashicorp/aws 6.56.0
    (in .terraform/providers) does not match any of the checksums recorded in the dependency lock file
  - registry.terraform.io/hashicorp/tls: the cached package for registry.terraform.io/hashicorp/tls 4.3.0
    (in .terraform/providers) does not match any of the checksums recorded in the dependency lock file
```

같은 PR의 다른 기존 모듈들(`backend_service` 등) job은 전부 정상 통과했다.

### 원인

`.terraform.lock.hcl`은 `terraform init`을 실행한 **로컬 머신의 플랫폼용 체크섬만** 기록한다.
이 코드는 macOS(darwin_arm64)에서 처음 `terraform init`을 실행해서 만들어졌고, 그 결과
lock 파일에는 darwin_arm64용 `h1:` 해시 하나만 들어갔다. GitHub Actions 러너는
linux_amd64라서, 거기서 받은 provider 패키지의 체크섬이 lock 파일에 없으니 "손상됐다"고
거부한 것이다.

기존 모듈들의 `.terraform.lock.hcl`을 보면 `h1:` 해시가 여러 개(darwin_arm64,
darwin_amd64, linux_amd64 등) 들어있는데, 이게 바로 이 문제를 피하려고 여러 플랫폼용으로
미리 lock을 걸어둔 것이었다.

```bash
grep -c "h1:" infra/modules/backend_service/.terraform.lock.hcl
# 3  ← 여러 플랫폼

grep -c "h1:" infra/modules/eks_cluster/.terraform.lock.hcl   # (문제 당시)
# 2  ← aws 1개 + tls 1개, 각각 darwin_arm64만
```

### 해결

새 모듈/환경 디렉터리에서 `terraform providers lock`으로 CI가 실제로 도는 플랫폼(및
팀에서 쓸 만한 다른 플랫폼)까지 명시적으로 lock한다. 네트워크 접속만 있으면 되고 AWS
자격증명은 필요 없다.

```bash
cd infra/modules/eks_cluster   # 또는 새로 추가한 디렉터리
terraform providers lock \
  -platform=linux_amd64 \
  -platform=darwin_amd64 \
  -platform=darwin_arm64
```

이후 `git diff .terraform.lock.hcl`로 `h1:`/`zh:` 해시가 추가된 것을 확인하고 커밋한다.

### 예방 — 새 모듈/환경을 추가할 때 항상

`terraform init -backend=false`만 실행하고 lock 파일을 커밋하면 이 문제가 재현된다.
새 디렉터리를 만들 때는 validate/test 이전에 아래를 먼저 실행하는 습관을 들인다.

```bash
terraform init -backend=false -input=false
terraform providers lock -platform=linux_amd64 -platform=darwin_amd64 -platform=darwin_arm64
```

## 2. Trivy가 새 EKS 리소스를 CRITICAL로 잡음 (`AVD-AWS-0040`/`AVD-AWS-0041`)

### 증상

`Verify Terraform / Trivy IaC and secret scan` job이 이렇게 실패했다.

```text
Tests: 2 (SUCCESSES: 0, FAILURES: 2)
Failures: 2 (HIGH: 0, CRITICAL: 2)
AWS-0040 (CRITICAL): Public cluster access is enabled.
AWS-0041 (CRITICAL): Cluster allows access from a public CIDR: 0.0.0.0/0
```

### 원인

`eks_cluster` 모듈의 `endpoint_public_access` 기본값을 `true`, `public_access_cidrs`
기본값을 `["0.0.0.0/0"]`로 짰다 — "팀 고정 IP/VPN 대역이 확정되기 전까지 kubectl 검증
편의를 위해 일단 전체 공개로 시작"이라는 판단이었다.

문제는 두 가지였다.

1. Trivy가 이걸 HIGH가 아니라 **CRITICAL**로 잡았고, `.github/workflows/terraform-verification.yml`의
   Trivy job은 `severity: HIGH,CRITICAL`에 `exit-code: 1`이라 CI를 그대로 막았다.
2. 이 저장소의 다른 모든 EC2(`backend_service`, `monitoring_ec2`, `load_test_runner`)는
   인바운드 포트가 하나도 없는 "SSM 전용" 패턴인데, EKS 컨트롤 플레인만 인터넷에 여는 건
   기존 보안 원칙과 어긋났다.

### 해결 — 예외 등록이 아니라 설계 변경

`infra/.trivyignore.yaml`에 예외를 추가해서 우회하지 않았다 (이미 있는 예외들도 전부
"S3 SSE로 충분하다", "단일 NAT를 통해야 한다" 같은 구체적 근거가 있는 것들이지, 발견된
CRITICAL을 그냥 지우는 용도가 아니다). 대신 접근 방식 자체를 EC2 패턴과 맞췄다.

- `eks_cluster` 모듈의 `endpoint_public_access` 기본값을 `false`로 바꿈.
- `dev-eks` 환경에 EC2와 동일한 SSM 전용 검증 bastion(public IP·SSH 없음)을 추가.
  bastion은 private subnet 안에 있어서 별도 포트포워딩 없이 바로 private endpoint에
  kubectl이 닿는다.
- Kubernetes RBAC은 AWS IAM과 별개라, `admin_principal_arns` 변수로 EKS Access Entry를
  등록해야 실제로 kubectl 권한이 생긴다는 것도 이 과정에서 확인했다 — 네트워크가 열려
  있어도 이 목록에 없으면 `Unauthorized`다.

자세한 설계와 SSM 검증 절차는 [`environments/dev-eks/README.md`](environments/dev-eks/README.md)의
"접근 모델" 절을 참고한다.

`public_access_cidrs`/`endpoint_public_access`는 변수로는 남겨뒀다 — bastion 접근이 없는
운영자가 일시적으로 노트북에서 직접 붙어야 하는 예외 상황을 위한 것이지, 기본 운영
경로가 아니다.

### 예방 — 새 리소스가 인터넷에 뭔가를 열 때

- Trivy가 뭔가를 잡으면, 먼저 "이 저장소의 기존 원칙(비공개 우선 + SSM)과 왜 다른가"를
  먼저 확인한다. 예외 등록은 최후 수단이고, 그마저도 만료일과 구체적 근거가 있어야
  `infra/.trivyignore.yaml`에 들어간다.
- HIGH/CRITICAL 등급은 CI가 그대로 실패시킨다는 걸 계획 단계에서 감안한다 — "나중에
  팀 IP 확정되면 좁히면 된다"는 판단만으로는 CI가 통과하지 않는다.
