# dev-load-test 운영 인계

`dev-load-test`는 한 번에 하나의 disposable runtime을 대상으로 부하·복구 테스트를 실행할
때만 생성하는 종속 Terraform Root다. 대상은 EC2 `dev-runtime` 또는 EKS `dev-eks`이며,
Load Runner EC2, Runner 전용 Security Group과 IAM, raw evidence S3 버킷은 대상 runtime과
다른 `dev-load-test/terraform.tfstate`에서 관리한다.

이 Root는 독립 서비스 환경이 아니다. `dev`의 VPC·app subnet과 선택한 runtime State의
RDS·Redis Security Group 및 Redis IAM 식별자를 원격 State output으로 읽는다. 따라서
선택한 runtime을 먼저 생성하고 정상 상태를 확인한 뒤에만 plan/apply한다.

> 현재 코드 분리 시점에는 `dev-load-test`를 실제 AWS에 apply하지 않았다. 이 문서는
> 다음 부하 테스트에서 재생성하기 위한 runbook이며, 명령 예시는 실행 기록이 아니다.

## State와 수명주기

생성 순서는 다음과 같다.

```text
dev → (dev-runtime 또는 dev-eks) → dev-load-test
```

삭제 순서는 반대다.

```text
dev-load-test → (dev-runtime 또는 dev-eks)
```

EKS 비교를 수행할 때의 삭제 순서는 `dev-load-test → dev-eks`다. `dev-runtime`과
`dev-eks`를 동시에 생성해 같은 persistent app route table이나 논리적 데이터 tier를
공유하지 않는다.

`dev-load-test`가 남아 있는 동안 선택한 runtime을 먼저 destroy하면 Runner Security Group의
RDS·Redis 참조 때문에 삭제가 실패하거나 테스트 실행 중 대상이 사라질 수 있다.

이 Root가 생성하는 주요 리소스는 다음과 같다.

- private subnet의 단일 Load Runner EC2와 암호화된 gp3 root volume
- inbound가 없는 Runner Security Group
- SSM Instance Profile과 최소권한 runtime IAM policy
- raw k6 결과용 private S3 bucket, SSE-S3, 30일 lifecycle
- unattached evidence operator read policy

Redis의 load-test IAM RBAC 사용자는 Redis User Group과 함께 선택한 runtime의
`backend_data` 모듈이 관리한다. `dev-load-test`는 사용자 ARN과 replication group ARN을
읽어 Runner의 `elasticache:Connect` 권한만 구성한다.

## Runtime target contract

동일한 Runner와 evidence 계약을 유지하면서 `runtime_state_key`만 바꾼다.

| 비교 대상 | `runtime_state_key` | 데이터/SG 소유자 |
| --- | --- | --- |
| EC2 ASG | `dev-runtime/terraform.tfstate` | `dev-runtime` |
| EKS Backend | `dev-eks/terraform.tfstate` | `dev-eks` |

두 runtime State는 동시에 존재하면 안 된다. `dev-load-test`는 두 target의 output 이름과
형식을 동일하게 소비한다.

## 최초 분리 후 로컬 설정

실제 설정 파일은 Git에 커밋하지 않는다.

```bash
cp infra/environments/dev-load-test/backend.hcl.example \
  infra/environments/dev-load-test/backend.hcl
cp infra/environments/dev-load-test/terraform.tfvars.example \
  infra/environments/dev-load-test/terraform.tfvars
```

기존 `infra/environments/dev-runtime/terraform.tfvars`에 아래 값이 남아 있다면 실제 값을
출력하거나 저장소에 복사하지 말고, 사용자가 새 `dev-load-test/terraform.tfvars`로 수동
이동한 뒤 기존 파일에서 제거한다.

- `test_db_secret_arn`
- `load_runner_source_commit_sha`
- `load_runner_instance_type`
- `load_runner_botocore_version`
- 별도로 재정의한 `k6_image_reference`

State 운영자 정책에는 `dev-load-test/terraform.tfstate`와 해당 `.tflock`에 대한 권한이
추가되어야 한다. State 객체에는 `GetObject`·`PutObject`, lock 객체에만
`GetObject`·`PutObject`·`DeleteObject`를 허용한다. IAM Identity Center Permission Set을
갱신하고 재프로비저닝한 뒤 새 SSO 세션을 사용한다.

## Plan

먼저 `runtime_state_key`가 가리키는 State가 필요한 output을 제공하는지와 실제 Runtime이
정상인지 확인한다. EKS 비교에서는 `dev-eks` apply 후에만 아래 값을 사용한다.

```bash
export AWS_PROFILE=kdt-travel-terraform
aws sts get-caller-identity --profile "$AWS_PROFILE"

terraform -chdir=infra/environments/dev-load-test init \
  -backend-config=backend.hcl

AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-load-test plan \
  -var-file=terraform.tfvars \
  -out=dev-load-test.tfplan

terraform -chdir=infra/environments/dev-load-test show dev-load-test.tfplan
```

Plan에서 다음을 확인한다.

- backend key가 `dev-load-test/terraform.tfstate`다.
- EC2는 1대이며 public IP가 없다.
- Runner SG에는 ingress가 없다.
- HTTPS와 VPC resolver DNS 외 일반 CIDR egress가 없다.
- PostgreSQL 5432와 Redis 6379는 Security Group reference를 사용한다.
- k6 이미지는 정확한 digest로 고정된다.
- Runner IAM은 지정 test DB Secret만 읽고 Redis IAM user/replication group에만 연결한다.
- 선택한 runtime 소유 리소스의 create/update/delete/replace가 없다.
- EKS 비교에서는 `runtime_state_key=dev-eks/terraform.tfstate`가 plan과 output에 기록된다.

`apply`는 비용과 IAM·네트워크 상태를 바꾸므로 saved plan 검토 후 별도 승인을 받아 실행한다.

```bash
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-load-test apply dev-load-test.tfplan
```

apply 후 `load_runner_instance_id`를 SSM target으로 사용한다. 이 모듈은 k6 daemon을 상시
실행하지 않는다. user data는 Docker, 검토된 source commit과 고정 k6 이미지를 준비하고,
실제 테스트는 SSM Run Command와 `scripts/loadtest/aws/` orchestration이 시작한다.

## 테스트 종료와 destroy

먼저 evidence를 외부에 보존하고 `load_test_evidence_operator_read_policy_arn`이 Permission
Set이나 Role에 연결되어 있다면 detach와 재프로비저닝을 완료한다. 연결된 policy는
Terraform이 삭제할 수 없다.

```bash
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-load-test plan -destroy \
  -var-file=terraform.tfvars \
  -out=dev-load-test-destroy.tfplan

terraform -chdir=infra/environments/dev-load-test show \
  dev-load-test-destroy.tfplan

# 별도 승인 후에만 실행
AWS_PROFILE="$AWS_PROFILE" \
terraform -chdir=infra/environments/dev-load-test apply \
  dev-load-test-destroy.tfplan

terraform -chdir=infra/environments/dev-load-test state list
```

`dev-load-test` State가 비고 Runner EC2·evidence bucket·Runner IAM/SG가 제거된 것을 확인한
뒤에만 선택한 runtime destroy를 진행한다.

## EKS 비교 주의사항

EKS에서는 `dev-eks`의 RDS·Redis·SG outputs가 준비된 뒤 동일한 Runner를 재사용한다.
Runner를 EKS용으로 중복 생성하지 않으며, 대상 전환은 `runtime_state_key` 변경과 새
saved plan 검토로만 수행한다.
