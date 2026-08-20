# dev-eks 운영 인계

`dev-eks`는 SCRUM-10 범위의 EKS 클러스터(컨트롤 플레인 + 관리형 노드그룹 + 클러스터
IRSA OIDC provider) 전용 Terraform Root다. `dev-eks/terraform.tfstate`에서 독립적으로
관리하며, `dev`의 VPC·app subnet만 원격 State output으로 읽는다.

> 이 세션에는 `kdt-travel-terraform` 권한이 없어 실제 `apply`를 실행하지 않았다. 코드
> 작성과 `-backend=false` validate, mock_provider 기반 `terraform test`까지만 이 세션에서
> 완료했다. `plan`/`apply`는 권한 있는 사람이 아래 Plan 절차로 진행한다.

## State와 의존성

```text
dev → dev-eks
```

`dev-load-test`(SCRUM-21)가 `dev`와 `dev-runtime`에 나란히 새 State를 분리한 선례를
따라, `dev-eks`도 `dev-runtime`에는 의존하지 않는다. EKS 클러스터는 `dev-runtime`(EC2
Runtime)이 떠 있든 삭제되어 있든 독립적으로 생성·삭제할 수 있어야 한다.

RDS/Redis 보안그룹을 EKS 노드에 연결하는 작업(`runtime_security` 확장, `dev-runtime`
원격 State 참조 추가)은 SCRUM-11 범위다. 이 Root는 그 의존성을 아직 추가하지 않는다.

이 Root가 생성하는 주요 리소스는 `infra/modules/eks_cluster/`가 담당한다.

- private app subnet의 EKS 컨트롤 플레인(`endpoint_private_access = true`)
- 컨트롤 플레인 로그 5종 전체 활성화, 전용 KMS 키로 Secrets 암호화
- private app subnet의 관리형 노드그룹 1대(`t3.medium`, public IP 없음)
- 클러스터 자체의 IRSA용 OIDC provider (SCRUM-11에서 워크로드 Role을 여기에 연결)

## 최초 설정

실제 설정 파일은 Git에 커밋하지 않는다.

```bash
cp infra/environments/dev-eks/backend.hcl.example \
  infra/environments/dev-eks/backend.hcl
cp infra/environments/dev-eks/terraform.tfvars.example \
  infra/environments/dev-eks/terraform.tfvars
```

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
- 컨트롤 플레인과 노드그룹 모두 app(private) subnet에만 위치하고 노드에 public IP가
  없다.
- 컨트롤 플레인 로그 5종(`api`/`audit`/`authenticator`/`controllerManager`/
  `scheduler`) 전체가 활성화된다.
- Secrets 암호화가 새로 생성되는 전용 KMS 키를 사용한다(S3 SSE용 기존 예외
  `AVD-AWS-0132`와 무관).
- `public_access_cidrs`가 `terraform.tfvars`의 의도된 값(기본은 임시로 `0.0.0.0/0`)과
  일치한다. Trivy가 이 값을 HIGH로 잡을 수 있는데, 팀 IP/VPN 대역이 확정되기 전까지는
  예외 처리 없이 변수로만 관리하기로 결정했다.
- 노드그룹이 `t3.medium` 1대(min=desired=max=1)다.

`apply`는 비용과 IAM·네트워크 상태를 바꾸므로 saved plan 검토 후 별도 승인을 받아
실행한다.

```bash
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks apply dev-eks.tfplan
```

apply 후 `cluster_name` output으로 kubeconfig를 생성하고 `kubectl get nodes`로 노드가
`Ready` 상태로 조인했는지 확인한다.

```bash
aws eks update-kubeconfig \
  --name "$(terraform -chdir=infra/environments/dev-eks output -raw cluster_name)" \
  --region ap-northeast-2 \
  --profile "$AWS_PROFILE"

kubectl get nodes
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
