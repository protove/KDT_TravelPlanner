# dev-eks 운영 인계

`dev-eks`는 SCRUM-10 범위의 EKS 클러스터(컨트롤 플레인 + 관리형 노드그룹 + 클러스터
IRSA OIDC provider 통) 전용 Terraform Root다. `dev-eks/terraform.tfstate`에서 독립적으로
관리하며, `dev`의 VPC·app subnet만 원격 State output으로 읽는다.

> 이 세션에는 `kdt-travel-terraform` 권한이 없어 실제 `apply`를 실행하지 않았다. 코드
> 작성과 `-backend=false` validate, mock_provider 기반 `terraform test`까지만 이 세션에서
> 완료했다. `plan`/`apply`는 권한 있는 사람이 아래 Plan 절차로 진행한다.

## 접근 모델: 네트워크와 권한은 별개다

이 클러스터에 kubectl로 들어가려면 두 가지가 각각 통과되어야 한다.

1. **네트워크** — API 서버에 도달할 수 있는가
2. **권한(Kubernetes RBAC)** — 도달했다 쳐도, 그 사람의 AWS IAM 신원을 클러스터가
   알고 허락하는가. 이건 AWS IAM 권한과 완전히 별개다. `AdministratorAccess`가 있어도
   여기 등록 안 되어 있으면 kubectl은 그냥 `Unauthorized`를 반환한다.

### 네트워크: 기본값은 완전 비공개

이 저장소의 다른 모든 EC2(`backend_service`, `monitoring_ec2`)와 동일하게, EKS
컨트롤 플레인도 **인터넷에 열린 포트가 하나도 없는 걸 기본값**으로 한다
(`endpoint_public_access = false`). 대신 이 Root가 같이 만드는 **SSM 전용 bastion**
EC2를 통해 검증한다 — bastion도 public IP·SSH 없이 SSM Session Manager로만 접속하고,
private app subnet 안에 있어서 별도 포트포워딩 없이 바로 private endpoint에 kubectl이
닿는다.

`public_access_cidrs`/`endpoint_public_access` 변수는 남겨뒀지만, 이건 "bastion 접근이
없는 운영자가 급하게 자기 노트북에서 붙어야 하는" 예외 상황을 위한 **의도적이고 일시적인
opt-in**이지 기본 운영 경로가 아니다. 켜두는 채로 방치하지 않는다.

### 권한: Access Entry로 명시 등록

`admin_principal_arns` 변수에 IAM 역할 ARN을 넣으면, 그 역할을 가진 사람 전원이 클러스터
관리자 권한을 받는다. 이상적으로는 팀이 EC2 SSM 접속에 실제로 쓰고 있는, **가장 좁은
권한의** 공용 IAM Identity Center 역할 하나만 넣으면 된다 — 그러면 "그 bastion에 SSM
접속 가능한 사람 = kubectl 가능한 사람"으로 그대로 일치한다.

**주의**: `AdministratorAccess` 같은 계정 전체 관리자 역할을 그대로 넣지 않는다. 이
Root를 만들며 실제로 확인해보니, 조장님이 EC2 SSM 접속에 `AdministratorAccess` Permission
Set을 쓰고 있었는데, 이걸 그대로 등록하면 "AWS 계정 관리자 권한이 있는 사람은 전부 자동으로
EKS 클러스터 관리자"가 되어버려 `infra/README.md`의 "Bootstrap/일상 실행/Runtime 권한을
분리한다"는 최소 권한 원칙과 어긋난다. apply 전에 인프라 담당자가 실제로 어떤 Permission
Set을 쓸지 확정한다(전용 SSM 접속 역할이 따로 없다면, 이번 기회에 하나 만드는 것도
고려한다). 비워두면 apply를 실제로 실행한 신원만 자동으로 관리자 권한을 받는다(EKS 기본
동작, `bootstrap_cluster_creator_admin_permissions = true`).

## State와 의존성

```text
dev → dev-eks
```

`dev-load-test`(SCRUM-21)가 `dev`와 `dev-runtime`에 나란히 새 State를 분리한 선례를
따라, `dev-eks`도 `dev-runtime`에는 의존하지 않는다. EKS 클러스터는 `dev-runtime`(EC2
Runtime)이 떠 있든 삭제되어 있든 독립적으로 생성·삭제할 수 있어야 한다.

RDS/Redis 보안그룹을 EKS 노드에 연결하는 작업(`runtime_security` 확장, `dev-runtime`
원격 State 참조 추가)은 SCRUM-11 범위다. 이 Root는 그 의존성을 아직 추가하지 않는다.

이 Root가 생성하는 주요 리소스:

`infra/modules/eks_cluster/`가 담당하는 것:

- private app subnet의 EKS 컨트롤 플레인, 기본값 완전 비공개
  (`endpoint_private_access = true`, `endpoint_public_access = false`)
- 컨트롤 플레인 로그 5종 전체 활성화, 전용 KMS 키로 Secrets 암호화
- `access_config { authentication_mode = "API" }` — legacy aws-auth ConfigMap 없이
  Access Entry만으로 인증
- private app subnet의 관리형 노드그룹 1대(`t3.medium`, public IP 없음)
- 클러스터 자체의 IRSA용 OIDC provider (SCRUM-11에서 워크로드 Role을 여기에 연결)
- `admin_principal_arns`에 넣은 ARN마다 `AmazonEKSClusterAdminPolicy` Access Entry

이 Root(`dev-eks/main.tf`)가 직접 만드는 것:

- SSM 전용 검증 bastion EC2(`t3.micro`, public IP·SSH 없음, inbound 없음)
- bastion용 IAM 역할(`AmazonSSMManagedInstanceCore`만 부착)과 보안그룹
- EKS 클러스터 보안그룹에 "bastion에서만 443 허용" 인바운드 규칙 1개

## 최초 설정

실제 설정 파일은 Git에 커밋하지 않는다.

```bash
cp infra/environments/dev-eks/backend.hcl.example \
  infra/environments/dev-eks/backend.hcl
cp infra/environments/dev-eks/terraform.tfvars.example \
  infra/environments/dev-eks/terraform.tfvars
```

`terraform.tfvars`의 `admin_principal_arns`에 팀이 이미 쓰는 공용 IAM 역할 ARN을
채워 넣는다. 비워두면 apply를 실행한 신원만 클러스터에 들어갈 수 있다.

State 운영자 정책에는 `dev-eks/terraform.tfstate`와 해당 `.tflock`에 대한 권한이
추가되어야 한다. State 객체에는 `GetObject`·`PutObject`, lock 객체에만
`GetObject`·`PutObject`·`DeleteObject`를 허용한다.

## Plan

```bash
export AWS_PROFILE=kdt-travel-terraform
aws sts get-caller-identity --profile "$AWS_PROFILE"

terraform -chdir=infra/environments/dev-eks init \
  -backend-config=backend.hcl

AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks plan \
  -var-file=terraform.tfvars \
  -out=dev-eks.tfplan

terraform -chdir=infra/environments/dev-eks show dev-eks.tfplan
```

Plan에서 다음을 확인한다.

- backend key가 `dev-eks/terraform.tfstate`다.
- 신규 생성만 있고 `dev`/`dev-runtime`/`dev-load-test` 소유 리소스의 create/update/
  delete/replace가 전혀 없다 — `dev-eks`는 이들과 독립적이어야 하므로 조금이라도
  건드리면 설계가 잘못된 것이다.
- 컨트롤 플레인, 노드그룹, bastion 전부 app(private) subnet에만 위치하고 public IP가
  없다. `endpoint_public_access`가 `terraform.tfvars`에서 명시적으로 켜지 않은 한
  `false`다.
- 컨트롤 플레인 로그 5종(`api`/`audit`/`authenticator`/`controllerManager`/
  `scheduler`) 전체가 활성화된다.
- Secrets 암호화가 새로 생성되는 전용 KMS 키를 사용한다(S3 SSE용 기존 예외
  `AVD-AWS-0132`와 무관).
- `admin_principal_arns`에 넣은 ARN 수만큼 Access Entry가 생성된다.
- 노드그룹이 `t3.medium` 1대(min=desired=max=1)다.

`apply`는 비용과 IAM·네트워크 상태를 바꾸므로 saved plan 검토 후 별도 승인을 받아
실행한다.

```bash
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks apply dev-eks.tfplan
```

## apply 후 검증 (SSM bastion 경유)

컨트롤 플레인이 기본적으로 비공개라, 자기 노트북에서 바로 kubectl을 붙일 수 없다.
bastion에 SSM으로 접속해서 그 안에서 검증한다.

```bash
BASTION_ID="$(terraform -chdir=infra/environments/dev-eks output -raw bastion_instance_id)"

AWS_PROFILE="$AWS_PROFILE" \
aws ssm start-session --target "$BASTION_ID" --region ap-northeast-2
```

세션이 열리면 bastion 안에서:

```bash
CLUSTER_NAME="<terraform output cluster_name 값>"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region ap-northeast-2
kubectl get nodes
```

`admin_principal_arns`에 등록되지 않은 신원으로 접속하면 네트워크는 뚫려도
`kubectl`이 `Unauthorized`를 반환한다 — 이건 버그가 아니라 의도된 동작이다.

### 예외: bastion 없이 노트북에서 직접 붙어야 할 때만

정말 필요한 경우에만, 일시적으로 켰다가 검증이 끝나면 바로 끄고 재적용한다.

```bash
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks apply \
  -var-file=terraform.tfvars \
  -var endpoint_public_access=true \
  -var 'public_access_cidrs=["<본인 공인 IP>/32"]'

# 검증 후 반드시 원상복구
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks apply -var-file=terraform.tfvars
```

## 후속 범위 (SCRUM-11)

- `runtime_security`에 EKS 노드 보안그룹을 추가하고 `dev-runtime`의 RDS/Redis SG에
  연결.
- `dev-eks`가 `dev-runtime` 원격 State(RDS/Redis SG, Redis IAM 식별자)를 추가로 읽을지
  여부는 그 시점에 다시 결정한다(`dev-load-test`가 `dev-runtime`을 읽는 것과 같은
  패턴이 될 가능성이 높다).
- `profile_image_runtime_policy_arn`을 IRSA 역할에 연결.
- 실제 backend 워크로드 배포와 통합 검증(SCRUM-12).

## 종료와 destroy

검증이 끝나면 `dev-runtime` 관행대로 `plan -destroy` 검토 후 별도 승인을 받아
삭제한다.

```bash
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks plan -destroy \
  -var-file=terraform.tfvars \
  -out=dev-eks-destroy.tfplan

terraform -chdir=infra/environments/dev-eks show dev-eks-destroy.tfplan

# 별도 승인 후에만 실행
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks apply dev-eks-destroy.tfplan
```
