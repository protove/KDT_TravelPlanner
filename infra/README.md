# KDT TravelPlanner Terraform

이 디렉터리는 Terraform State 기반 인프라와 애플리케이션 인프라를 분리하고, `dev`와 `prod`가 서로 다른 Root와 State를 사용하도록 구성한다.

## 디렉터리 구조

```text
infra/
├── bootstrap/                         # State S3 최초 생성 전용 Root
├── environments/
│   ├── dev/                           # 개발 환경 Root
│   └── prod/                          # 운영 환경 Root
└── modules/
    ├── terraform_state_backend/       # State S3와 최소 State 접근 정책
    └── profile_image/                 # 이미지 S3, CloudFront OAC, Runtime Policy
```

모듈은 AWS Provider를 설정하지 않는다. 각 Root의 `providers.tf`가 Region, 허용 AWS Account ID와 공통 태그를 설정한다.

## 파일 역할

| 파일 | 역할 | 자격증명 포함 여부 |
|---|---|---|
| `backend.tf` | Terraform State 저장 방식 선언 | 포함하지 않음 |
| `backend.hcl` | State 버킷, key, Region, lock 설정 | 포함하지 않음 |
| `providers.tf` | AWS Region, 허용 Account ID, 기본 태그 | 포함하지 않음 |
| `terraform.tfvars` | 환경별 비민감 입력값 | 비밀값 금지 |
| `main.tf` | 기능 모듈 조합 | 포함하지 않음 |

AWS 인증은 `AWS_PROFILE` 또는 AWS SDK 기본 자격증명 체인으로만 제공한다. Access Key, Secret Key, Session Token과 SSO Profile 이름을 Terraform 파일에 기록하지 않는다.

## 보안 경계

- State S3와 프로필 이미지 S3는 서로 다른 버킷이다.
- State S3는 SSE-S3, Versioning, Public Access Block, TLS 강제와 `prevent_destroy`를 적용한다.
- 일상 Terraform 실행 Role은 State 객체를 읽고 갱신할 수 있지만 삭제할 수 없다.
- 일상 Terraform 실행 Role은 `<state-key>.tflock`만 삭제할 수 있다.
- Bootstrap 관리 권한, 일상 Terraform 실행 권한과 애플리케이션 Runtime 권한을 분리한다.
- Provider의 `allowed_account_ids`가 로그인한 AWS 계정이 예상 계정과 다르면 실행을 중단한다.
- 프로필 이미지는 공개 CloudFront URL로 제공된다. UUID key는 접근 제어가 아니며 민감한 이미지를 저장하지 않는다.

## 사전 조건

- Terraform `>= 1.10, < 2.0`
- AWS CLI v2
- IAM Identity Center 프로필과 Bootstrap에 필요한 AWS 권한
- 사용자 AWS Account ID

```bash
aws sso login --profile kdt-travel-bootstrap
aws sts get-caller-identity --profile kdt-travel-bootstrap
```

`Account`가 `terraform.tfvars`의 `aws_account_id`와 정확히 같은지 확인한다.

## 1. State S3 최초 Bootstrap

State 버킷은 자신이 저장될 S3 Backend보다 먼저 존재해야 한다. 최초 한 번은 `infra/bootstrap`을 로컬 State로 실행한다.

```bash
cp infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap fmt -check
terraform -chdir=infra/bootstrap validate
AWS_PROFILE=kdt-travel-bootstrap \
  terraform -chdir=infra/bootstrap plan \
  -out=bootstrap.tfplan
```

Plan에는 Terraform State 버킷 관련 리소스만 있어야 한다. 계획을 사람이 검토한 뒤 저장된 plan을 적용한다.

```bash
AWS_PROFILE=kdt-travel-bootstrap \
  terraform -chdir=infra/bootstrap apply bootstrap.tfplan
```

`-auto-approve`를 사용하지 않는다. Bootstrap Root에서는 State 버킷 외 리소스를 생성하지 않는다.

## 2. Bootstrap State를 원격 S3로 이전

버킷 생성 후 `infra/bootstrap/backend.tf.example`을 `backend.tf`로 복사한다. State 버킷이 존재하기 전에는 이름을 바꾸지 않는다.

```hcl
terraform {
  backend "s3" {}
}
```

`backend.hcl.example`을 `backend.hcl`로 복사하고 실제 State 버킷 이름을 입력한다. 이 파일에는 자격증명이나 Profile 이름을 넣지 않는다.

```bash
cp infra/bootstrap/backend.hcl.example infra/bootstrap/backend.hcl
AWS_PROFILE=kdt-travel-bootstrap \
  terraform -chdir=infra/bootstrap init \
  -migrate-state \
  -backend-config=backend.hcl
```

마이그레이션 전에 로컬 State를 안전한 위치에 백업한다. 이전 후 `terraform state pull`이 성공하고 State S3에 `bootstrap/terraform.tfstate`가 존재하는지 확인한다.

## 3. dev 원격 Backend 초기화와 Plan

```bash
cp infra/environments/dev/backend.hcl.example infra/environments/dev/backend.hcl
cp infra/environments/dev/terraform.tfvars.example infra/environments/dev/terraform.tfvars

AWS_PROFILE=kdt-travel-terraform \
  terraform -chdir=infra/environments/dev init \
  -backend-config=backend.hcl

AWS_PROFILE=kdt-travel-terraform \
  terraform -chdir=infra/environments/dev plan \
  -var-file=terraform.tfvars
```

Plan에서 교체·삭제가 없고 예상 리소스만 생성되는지 검토한 뒤 저장된 plan을 적용한다.

```bash
AWS_PROFILE=kdt-travel-terraform \
  terraform -chdir=infra/environments/dev apply dev-profile-image.tfplan
```

현재 dev 이미지 S3, CloudFront와 Runtime Policy는 적용되어 있으며 `terraform plan` 결과가 `No changes`임을 확인했다. prod는 별도 승인 전까지 정적 검증만 수행한다.

## 애플리케이션 연결 출력

이미지 인프라가 별도로 승인·적용된 후 다음 output을 사용한다.

| Terraform output | 애플리케이션 설정 |
|---|---|
| `profile_image_bucket_name` | `PROFILE_IMAGE_STORAGE_BUCKET` |
| `profile_image_public_base_url` | `PROFILE_IMAGE_PUBLIC_BASE_URL` |
| `profile_image_runtime_policy_arn` | 개발 SSO Permission Set 또는 운영 Runtime Role 연결 |

AWS S3에서는 `PROFILE_IMAGE_STORAGE_PATH_STYLE_ACCESS_ENABLED=false`를 사용한다.

`profile_image_runtime_policy_arn`은 생성만 되고 자동 연결되지 않는다. 개발용 `KDT-Dev-Runtime-Test` Permission Set에는 동일한 최소권한 인라인 정책을 유지하거나, 생성된 고객 관리형 정책을 이름과 `/` 경로로 연결한다. 두 방식을 중복 적용하지 않는다.

## 금지 사항

- `terraform.tfstate`, 저장된 plan, 실제 tfvars와 backend 설정을 Git에 커밋하지 않는다.
- SSO 임시 키나 장기 Access Key를 Terraform 코드·환경 예제·GitHub Actions에 넣지 않는다.
- `terraform apply -auto-approve`를 사용하지 않는다.
- 다른 AWS Account에서 `allowed_account_ids`를 변경해 우회하지 않는다.
- 실행 중인 작업 확인 없이 `terraform force-unlock`을 사용하지 않는다.
- 공개 CDN URL을 인증 또는 권한 확인 수단으로 사용하지 않는다.

## 로컬·CI 검증

```bash
terraform fmt -check -recursive infra
terraform -chdir=infra/bootstrap init -backend=false
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/environments/dev init -backend=false
terraform -chdir=infra/environments/dev validate
terraform -chdir=infra/environments/prod init -backend=false
terraform -chdir=infra/environments/prod validate
terraform -chdir=infra/modules/terraform_state_backend test
terraform -chdir=infra/modules/profile_image test
```

CI는 실제 AWS 자격증명을 전달받지 않으며 AWS plan/apply를 실행하지 않는다.

Trivy의 WAF(`AVD-AWS-0011`)와 고객 관리 KMS key(`AVD-AWS-0132`) 권고는 현재 확정 범위와 충돌하므로 `infra/.trivyignore.yaml`에 대상 파일·근거·만료일을 기록한다. 만료 전 WAF 비용 통제와 KMS 운영 책임을 다시 검토하며, 그 밖의 HIGH/CRITICAL 결과는 CI를 실패시킨다.

자세한 최초 구성과 인증 구조는 다음 로컬 Reference를 참고한다.

- `reference/infrastructure/TERRAFORM_AWS_INITIAL_SETUP.md`
- `reference/infrastructure/TERRAFORM_CI_VERIFICATION.md`
- `reference/storage/AWS_SSO_LOCAL_AND_RUNTIME_CREDENTIALS.md`
- `reference/storage/PROFILE_IMAGE_AWS_BACKEND_RUNTIME_SETUP.md`
