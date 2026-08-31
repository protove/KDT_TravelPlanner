# dev-eks 운영 인계

`dev-eks`는 EKS 클러스터(컨트롤 플레인 + 관리형 노드그룹 + 클러스터 IRSA OIDC provider),
EC2 ASG baseline과 동등한 RDS/ElastiCache data tier, 비교테스트용 Monitoring EC2를 함께
관리하는 Terraform Root다.
`dev-eks/terraform.tfstate`에서 독립적으로 관리하며, persistent `dev` State의 VPC·subnet·
route-table output만 읽는다. `dev-runtime`이나 `dev-observability` State를 읽지 않는다.

운영 자동화의 전체 계약은 [`DEV_EKS_DEPLOYMENT_AUTOMATION.md`](../../../reference/infrastructure/terraform/DEV_EKS_DEPLOYMENT_AUTOMATION.md),
SSM 인자·polling·복구 계약은 [`DEV_EKS_SSM_TRANSPORT_CONTRACT.md`](../../../reference/infrastructure/terraform/DEV_EKS_SSM_TRANSPORT_CONTRACT.md),
copy-safe 절차는 [`DEV_EKS_DEPLOYMENT_RUNBOOK.md`](../../../reference/infrastructure/terraform/DEV_EKS_DEPLOYMENT_RUNBOOK.md),
apply 후 검증과 비용 없는 폐기 절차는 [`DEV_EKS_EPHEMERAL_LIFECYCLE_RUNBOOK.md`](../../../reference/infrastructure/terraform/DEV_EKS_EPHEMERAL_LIFECYCLE_RUNBOOK.md)를 기준으로 한다.

이미 apply된 이 disposable 환경을 검증한 뒤 곧바로 폐기하는 v7 canonical 경로는
`scripts/eks/run-dev-eks-ephemeral-lifecycle.sh --autonomous`다. execute-task-plan 호출
뒤 사용자가 `DEV_EKS_*` 값을 export하거나 SSO를 갱신하거나 Terraform/Kubernetes hash를
입력하지 않는다. 이 entrypoint는 고정 capsule, refreshable SSO heartbeat, single-use
authorization receipt를 executor가 구성하고, 모든 결과를 Ingress-first cleanup으로
join한다. 아래의 수동 `deploy-dev-eks.sh` 명령은 새 환경을 의도적으로 apply할 때만 쓰는
legacy compatibility 경로다.

## 자동화된 apply 후 경로

Terraform apply 뒤의 Bastion 접속, snapshot 검증, action-time 치환, Namespace/Secret
bootstrap, platform/workload rollout, ALB hostname 확인은
[`scripts/eks/deploy-dev-eks.sh`](../../../scripts/eks/deploy-dev-eks.sh) 하나로
재개 가능하게 실행한다. 기본 경로는 다음 순서를 고정한다.

```text
Terraform saved-plan gate
  -> SSM prepare (bundle/contract/hash/render)
  -> Namespace + Secrets Manager -> Kubernetes Secret
  -> platform (AWS Load Balancer Controller / Metrics Server / Cluster Autoscaler)
  -> workload (Backend / monitoring)
  -> bounded Ingress wait
  -> CLOUDFLARE_CNAME_TARGET=<validated *.elb.amazonaws.com>
```

정상 실행에 필요한 non-secret 입력은 Backend ECR digest, Backend hostname,
frontend origin, AWS profile/region/account와 saved plan이다. Terraform plan은
파일 바이트의 SHA-256을 먼저 확인하고 아래 문구를 정확히 입력해야 한다.

```text
APPLY TERRAFORM $DEV_EKS_TERRAFORM_PLAN_SHA256
APPLY KUBERNETES $KUBERNETES_RENDER_SHA256
```

`--non-interactive`에서는 두 hash를 각각 `--terraform-plan-sha256`와
`--kubernetes-render-sha256`로 전달한다. `--yes`/`auto-approve` 우회는 제공하지
않는다. Backend image는 persistent `dev` State의
`backend_ecr_repository_url`과 정확히 일치하는 `@sha256:<64 lowercase hex>`여야 하며,
live `prepare`/`run`/`resume` preflight가 ECR digest 존재 여부를 Terraform apply와
action-values 업로드보다 먼저 확인한다. `prepare`는 완전한 read-only 모드가 아니다.
private run-prefix에 non-secret action-values를 S3로 업로드하고 Bastion에 SSM `prepare`
명령을 보내 bundle/contract/render를 확인하지만, Terraform apply나 Kubernetes apply는
수행하지 않는다. 이 run-prefix와 Bastion work directory는 명시적 resume을 위한 보존
경계다.
`resume --resume-run-id "$PREVIOUS_REMOTE_RUN_ID" --resume-from prepare|namespace-secret|platform|workload|ingress-wait`는
선택한 stage와 그 뒤의 모든 stage를 순서대로 실행한다. `prepare` 시작은 prepare를 다시
실행한 뒤 namespace-secret부터 이어가며, 다른 시작점은 해당 stage의 이전 postcondition·
bundle revision·values/render hash를 재검증한다. 모든 resume suffix에는 첫 Kubernetes
mutation 전에 `APPLY KUBERNETES` 뒤에 `$KUBERNETES_RENDER_SHA256`의 실제 값을 붙인 승인이 필요하다. run id가 없으면
임의의 stale 작업 디렉터리를 재사용하지 않도록 resume을 거부한다.
`dry-run`은 local structural validation만 수행하며 live AWS, Terraform State, S3, SSM,
Kubernetes를 호출하지 않는다. dry-run summary의 `provenance_check`는
`structural-only`로 표시된다.

SSM 원격 shell은 AWS CLI shorthand가 아니라 `jq -cn --arg`로 만든
`{"commands":["<one command>"]}` JSON을 `--parameters` 하나의 argv 값으로 전달한다.
`InvocationDoesNotExist`만 bounded retry하고, identity/status/`ResponseCode`가 맞지 않으면
다음 stage로 진행하지 않는다. summary에는 `local_run_id`, `remote_run_id`, `resume_from`,
`render_sha256`가 함께 남는다.

먼저 render hash를 만들고 검토하려면 다음처럼 `prepare`를 실행한다. 이 단계의 private
S3/SSM 효과와 run directory 보존은 의도된 resume 지원 동작이다. 결과 hash는 ignored
`evidence/eks-deploy/<run-id>/deployment-summary.json`의 `render_sha256`에서 확인한 뒤
`APPLY KUBERNETES` 뒤에 `$KUBERNETES_RENDER_SHA256`의 실제 값을 붙인 승인에 사용한다.

```bash
scripts/eks/deploy-dev-eks.sh \
  --mode prepare \
  --aws-profile "$AWS_PROFILE" \
  --region ap-northeast-2 \
  --expected-account-id "$AWS_ACCOUNT_ID" \
  --backend-image "$DEV_EKS_BACKEND_IMAGE" \
  --backend-hostname "$DEV_EKS_BACKEND_HOSTNAME" \
  --frontend-origin "$DEV_EKS_FRONTEND_ORIGIN"
```

```bash
scripts/eks/deploy-dev-eks.sh \
  --mode run \
  --aws-profile "$AWS_PROFILE" \
  --region ap-northeast-2 \
  --expected-account-id "$AWS_ACCOUNT_ID" \
  --terraform-plan infra/environments/dev-eks/dev-eks.tfplan \
  --terraform-plan-sha256 "$DEV_EKS_TERRAFORM_PLAN_SHA256" \
  --backend-image "$DEV_EKS_BACKEND_IMAGE" \
  --backend-hostname "$DEV_EKS_BACKEND_HOSTNAME" \
  --frontend-origin "$DEV_EKS_FRONTEND_ORIGIN"
```

실행 요약은 ignored `evidence/eks-deploy/<run-id>/deployment-summary.json`에
sanitized metadata만 남기며 Secret 값, private IP, raw SSM payload는 저장하지 않는다.
Cloudflare는 자동으로 변경하지 않는다. 최종 stdout의 `CLOUDFLARE_CNAME_TARGET`만
확인해 기존 공개 API CNAME의 target을 수동 갱신하고, ACM DNS validation 레코드는
건드리지 않는다.

> v5 source/test repair 자체는 IAM 변경이나 Terraform/Kubernetes architecture 변경을 하지
> 않는다. live recovery는 fresh State/no-drift checkpoint와 별도 S3/SSM 및 Kubernetes
> approval 뒤에만 진행한다. Terraform apply 승인과 Cloudflare DNS 변경은 이 문서가 대신하지
> 않는다.

현재 `20260824T133440Z-15798` incident가 `--parameters` client-side parser에서 멈춘 경우,
Terraform을 다시 실행하지 말고 읽기 전용 checkpoint 후 `--mode resume --resume-from prepare`
로 이어간다. 이전 run ID와 상세 명령은
[`DEV_EKS_SSM_TRANSPORT_CONTRACT.md`](../../../reference/infrastructure/terraform/DEV_EKS_SSM_TRANSPORT_CONTRACT.md)의
복구 절차를 따른다.

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

`dev-eks`와 `dev-runtime`은 같은 persistent app route table을 **순차적으로** 소유한다.
따라서 `dev-runtime` State가 리소스를 하나라도 보유한 동안에는 dev-eks plan/apply를
시작하지 않는다. 이번 실행은 사용자가 확인한 것처럼 dev-runtime State가 비어 있다는
전제에서 시작했지만, 실제 apply 직전 운영자가 아래 preflight를 다시 실행해야 한다.

```text
persistent dev State (읽기 전용)
  ├─ dev-runtime State: NAT/route + EC2 ASG (비어 있어야 함)
  └─ dev-eks State: NAT/route + EKS + RDS/Redis + bastion + Monitoring EC2
```

`dev-load-test`(SCRUM-21)가 환경별 State를 분리한 선례와 같은 방식이며, `dev-eks`는
`dev-runtime`이나 `dev-observability`의 remote State를 참조하지 않는다. EKS와 Monitoring
EC2가 자체 NAT를 소유하므로, 두 State가 동시에 같은 app route table의 default route를
관리하는 상황은 지원하지 않는다.

ephemeral lifecycle의 destroy 범위는 이 Root의 `dev-eks/terraform.tfstate` 주소와 해당
Kubernetes controller-owned 리소스뿐이다. persistent `dev` State, `dev-runtime`,
`dev-load-test`, VPC/subnet/ACM/ECR/profile-image/application Secrets Manager와 Cloudflare는
삭제·갱신 대상이 아니다.

`dev-eks`는 `backend_data` 모듈을 직접 소유하고 RDS/Redis를 생성한다. 데이터 SG는 EKS
Cluster SG에서 오는 TCP 5432/6379만 허용하며, `dev-runtime` remote State를 참조하지
않는다. 기본 VPC CNI에서 Pod가 노드 ENI SG를 사용하는 비교 조건을 유지하기 위한 설계다.

이 Root가 생성하는 주요 리소스:

`infra/modules/eks_cluster/`가 담당하는 것:

- private app subnet의 EKS 컨트롤 플레인, 기본값 완전 비공개
  (`endpoint_private_access = true`, `endpoint_public_access = false`)
- 컨트롤 플레인 로그 5종 전체 활성화, 전용 KMS 키로 Secrets 암호화
- `access_config { authentication_mode = "API" }` — legacy aws-auth ConfigMap 없이
  Access Entry만으로 인증
- private app subnet의 관리형 노드그룹(`t3.small`, min=2/desired=2/max=4, public IP 없음)
- 클러스터 자체의 IRSA용 OIDC provider (SCRUM-11에서 워크로드 Role을 여기에 연결)
- `admin_principal_arns`에 넣은 ARN마다 `AmazonEKSClusterAdminPolicy` Access Entry

이 Root(`dev-eks/main.tf`)가 직접 만드는 것:

- public subnet `[0]`의 EIP 1개와 NAT Gateway 1개, 모든 persistent app route table의
  `0.0.0.0/0` route
- SSM 전용 검증 bastion EC2(`t3.micro`, public IP·SSH 없음, inbound 없음)
- bastion용 IAM 역할(`AmazonSSMManagedInstanceCore` + EKS DescribeCluster +
  `kubernetes/monitoring` source snapshot S3 read + exact runtime Secret read)과 보안그룹
- bastion role의 전용 EKS Access Entry/`AmazonEKSClusterAdminPolicy` 연결
- EKS 클러스터 보안그룹에 "bastion에서만 443 허용" 인바운드 규칙 1개
- private Monitoring EC2(`kdt-travelplanner-dev-eks-monitoring-runtime`)와 environment-local
  S3/SSM endpoint
- private encrypted Single-AZ RDS PostgreSQL 17과 TLS-required single-node Redis
- RDS/Redis data SG와 EKS Cluster SG 전용 TCP 5432/6379 ingress
- `dev-runtime`과 동일한 database/cache/Redis IAM/load-test output contract
- Monitoring SG의 cluster-SG 전용 `tcp/9090`, `tcp/3100` ingress와 443/DNS egress
- `k8s/overlays/dev-eks`와 두 base의 source snapshot을 S3 `kubernetes/monitoring/`에 업로드

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

## 순차 preflight (반드시 먼저 실행)

`dev-runtime` backend 설정을 사용해 실제 State의 리소스 목록이 비어 있는지 확인한다.
출력이 한 줄이라도 있으면 즉시 중단하고 dev-runtime을 먼저 destroy한다. 이 단계는
`dev-eks` apply 승인의 일부이며, Monitoring EC2를 공용 환경으로 옮기거나 remote State를
추가하는 우회로가 아니다.

```bash
export AWS_PROFILE=kdt-travel-terraform
export AWS_REGION=ap-northeast-2

aws sts get-caller-identity --profile "$AWS_PROFILE"

terraform -chdir=infra/environments/dev-runtime init \
  -backend-config=backend.hcl \
  -reconfigure

RUNTIME_RESOURCES="$(AWS_PROFILE="$AWS_PROFILE" \
  terraform -chdir=infra/environments/dev-runtime state list)"
if [ -n "$RUNTIME_RESOURCES" ]; then
  printf '%s\n' "BLOCK: dev-runtime State is not empty:" "$RUNTIME_RESOURCES" >&2
  exit 1
fi
printf '%s\n' "PASS: dev-runtime State is empty; dev-eks may be planned next."

TARGET_KUBERNETES_VERSION="$(AWS_PROFILE="$AWS_PROFILE" \
  terraform -chdir=infra/environments/dev-eks show -json dev-eks.tfplan \
  | jq -er '.variables.kubernetes_version.value | select(type == "string")')"
aws eks describe-cluster-versions \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --cluster-type eks \
  --cluster-versions "$TARGET_KUBERNETES_VERSION" \
  --no-paginate \
  --output json \
  | jq -e --arg target "$TARGET_KUBERNETES_VERSION" '
      type == "object" and (.clusterVersions | type == "array") and
      (.clusterVersions | length == 1) and
      (.clusterVersions[0].clusterVersion == $target) and
      (.clusterVersions[0].clusterType == "eks") and
      (.clusterVersions[0].versionStatus == "STANDARD_SUPPORT")'
```

`terraform state list`가 실패하면 State를 비었다고 추정하지 않는다. backend 권한·lock·
경로를 먼저 고치고 다시 확인한다. `clusterVersions`가 비었거나 둘 이상이거나, target/version
identity가 다르거나, `clusterType`이 `eks`가 아니거나, `versionStatus`가
`STANDARD_SUPPORT`가 아니면 지원 여부를 통과시키지 않는다. `status` 같은 deprecated field만
있는 응답도 실패로 처리한다. apply 이후 `run --skip-terraform-apply`, `prepare`, `resume`은
동일한 검사를 `terraform output -raw cluster_version`에서 해석한 값으로 수행한다.

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
- 노드그룹이 `t3.small` 2대에서 시작하고 min/desired/max가 `2/2/4`다.
- NAT Gateway가 정확히 1개이고 모든 persistent `app_route_table_ids`에 default route를
  하나씩 추가한다. 기존 dev-runtime route를 update/delete/replace하지 않는다.
- RDS는 exact PostgreSQL 17 patch, `db.t4g.micro`, private/encrypted/Single-AZ,
  `travel_diary_dev`, `travel_planner`, RDS-managed master Secret을 사용한다.
- Redis는 Redis OSS 7.1, `cache.t4g.micro` 1개, at-rest/in-transit encryption,
  TLS required, password default user와 IAM load-test user를 유지한다.
- data SG ingress는 EKS Cluster SG reference만 사용하며 CIDR 기반 5432/6379 ingress가 없다.
- `dev-eks` outputs가 `dev-load-test`의 `runtime_state_key=dev-eks/terraform.tfstate`
  계약에 필요한 database/cache/Redis 식별자를 모두 제공한다.
- Monitoring bucket/role/parameter 이름이 `dev-eks` 전용이다. Monitoring EC2는 private IP만
  가지며, SG ingress는 cluster SG의 9090/3100만 허용하고 22/3000/public 9090은 없다.
- EKS Monitoring EC2의 Prometheus만 `0.0.0.0:9090` remote-write receiver를 사용하고,
  EC2 기본 profile은 `127.0.0.1:9090` 및 `ec2:DescribeInstances`를 그대로 유지한다.
- bastion role이 `kubernetes/monitoring` source snapshot prefix와 exact runtime Secret만 읽고,
  전용 Access Entry가 생성된다.
- saved plan의 `kubernetes_version`과 유일한 managed `aws_eks_cluster.values.version`이
  같은 `1.NN` 문자열인지 확인하고, 해당 target이 `clusterType=eks`와
  `versionStatus=STANDARD_SUPPORT`인지 확인한다. `EXTENDED_SUPPORT`, `UNSUPPORTED`,
  schema/transport/cardinality/identity 오류는 각각 구분해 중단한다.

`apply`는 비용과 IAM·네트워크 상태를 바꾸므로 saved plan 검토 후 별도 승인을 받아
실행한다.

```bash
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-eks apply dev-eks.tfplan
```

## legacy 수동 검증 (자동화 장애 시에만)

> 이 절차는 exact Terraform/Kubernetes hash gate와 staged resume 검증을 우회할 수 있는
> 비상 진단용 fallback이다. 정상적인 apply 후 경로는 위의
> `scripts/eks/deploy-dev-eks.sh`만 사용한다. 수동 `kubectl apply`는 자동화가 막힌 원인과
> 별도 운영자 승인을 기록한 경우에만 사용한다.

## apply 후 검증 (SSM bastion 경유)

컨트롤 플레인이 기본적으로 비공개라, 자기 노트북에서 바로 kubectl을 붙일 수 없다.
bastion에 SSM으로 접속해서 그 안에서 검증한다. Backend Secret은 별도 bootstrap gate를
통과한 뒤에만 생성하며, source snapshot에는 Secret 값이 포함되지 않는다.

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

MONITORING_BUCKET="<terraform output monitoring_config_bucket_name 값>"
rm -rf /tmp/travel-planner-monitoring
mkdir -p /tmp/travel-planner-monitoring
aws s3 cp "s3://${MONITORING_BUCKET}/kubernetes/monitoring/" \
  /tmp/travel-planner-monitoring/ --recursive

kubectl kustomize /tmp/travel-planner-monitoring >/tmp/travel-planner-dev-eks.rendered.yaml
kubectl diff -k /tmp/travel-planner-monitoring

# GATE-KUBERNETES-APPLY: Secret materialization과 diff 검토 후에만 실행
kubectl apply -k /tmp/travel-planner-monitoring
kubectl rollout status deployment/backend -n travel-planner --timeout=300s
kubectl rollout status deployment/kube-state-metrics \
  -n travel-planner-monitoring --timeout=180s
kubectl rollout status daemonset/alloy \
  -n travel-planner-monitoring --timeout=180s
kubectl get pods -n travel-planner-monitoring -o wide
```

Backend Pod annotation/label 계약은 `k8s/base/backend/deployment.yaml`이 소유한다.
Alloy는 Pod IP를 하드코딩하지 않고 annotation 기반으로 actuator 9091을 scrape한다.
Backend ECS JSON 파일은 Pod-local sidecar가 `/var/log/travel-planner/travel-planner.log`에서
읽고, 중앙 Alloy는 메트릭만 `http://monitoring.dev-eks.kdt-travelplanner.internal:9090/api/v1/write`
로 전송한다. 두 endpoint 모두 private 경로이며 Loki 로그 전송은 sidecar의
`http://monitoring.dev-eks.kdt-travelplanner.internal:3100/loki/api/v1/push`에서만 발생한다.

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

## 후속 범위

- Argo CD Application이 `k8s/overlays/dev-eks`를 직접 가리키도록 별도 작업에서 구성한다.
- Secret operator 도입 여부와 Backend Secret 자동화는 별도 보안 검토에서 결정한다.
- 실제 EC2 ASG 대 EKS 부하 비교와 결과 해석은 이 Terraform/Kustomize 변경과 분리한다.

## 종료와 destroy

비교테스트 결과 JSON, Grafana 캡처, k6 evidence와 필요한 Prometheus/Loki query 결과를
먼저 로컬 evidence에 export한다. 이 환경의 Monitoring 데이터는 장기 보존 대상이 아니며,
검증이 끝나면 `plan -destroy` 검토 후 별도 승인을 받아 삭제한다.

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
