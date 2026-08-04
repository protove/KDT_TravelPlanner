# dev-runtime 운영 인계

`dev-runtime`은 부하·배포·복구 실험을 수행할 때만 생성하는 비용 발생 State다. VPC, subnet, ECR, API 인증서, 애플리케이션 secret 컨테이너와 기존 profile image 리소스는 `dev` State에 남고, 아래 리소스만 별도로 생성·제거한다.

- NAT Gateway 1개와 app private subnet 기본 경로
- Internet-facing ALB와 Target Group
- private EC2 ASG `2/2/4`, Launch Template, CPU 60% Target Tracking
- PostgreSQL 17 Single-AZ RDS와 Redis OSS 7.1 단일 노드

이 Issue의 첫 인계 범위는 `plan`까지다. `apply`, smoke test, 부하 실험, `destroy`는 각각 별도 승인 후 실행한다.

## 사전 조건

1. `bootstrap` State를 먼저 plan해서 `dev-runtime/terraform.tfstate` 접근 key 추가만 발생하는지 확인한다.
2. `dev` State를 plan해서 기존 profile image 리소스의 delete, replace가 없는지 확인한다.
3. `dev`의 API ACM validation CNAME을 Cloudflare에 DNS only로 등록하고 인증서가 `ISSUED`인지 확인한다.
4. backend 이미지를 `dev` ECR에 push하고 실제 manifest digest를 구한다. `:tag`는 입력 검증에서 거부된다.
5. `backend_application_secret_arn`이 가리키는 secret에 아래 JSON 값을 운영자가 등록한다. 실제 값이나 파일은 저장소에 커밋하지 않는다.

```json
{
  "JWT_SECRET": "replace-me",
  "GOOGLE_OAUTH_CLIENT_ID": "replace-me",
  "GOOGLE_OAUTH_CLIENT_SECRET": "replace-me",
  "NAVER_OAUTH_CLIENT_ID": "replace-me",
  "NAVER_OAUTH_CLIENT_SECRET": "replace-me",
  "GOOGLE_MAPS_API_KEY": "replace-me"
}
```

RDS master password와 Redis auth token은 Terraform/AWS가 생성한다. Launch Template user data에는 secret 값이 없으며, 인스턴스 role로 부팅 시 Secrets Manager에서 읽는다.

## Operator plan

`backend.hcl.example`과 `terraform.tfvars.example`을 복사한 로컬 파일은 커밋하지 않는다. 서울 리전에서 제공되는 PostgreSQL 17 patch 목록을 plan 직전에 조회하고, 선택한 정확한 버전을 `postgres_engine_version`에 기록한다.

```bash
aws rds describe-db-engine-versions \
  --region ap-northeast-2 \
  --engine postgres \
  --query 'DBEngineVersions[?starts_with(EngineVersion, `17.`)].EngineVersion' \
  --output text

terraform init -backend-config=backend.hcl
terraform plan -var-file=terraform.tfvars -out=dev-runtime.tfplan
terraform show dev-runtime.tfplan
```

plan 검토 시 다음을 모두 확인한다.

- backend EC2 network interface에 public IP가 없다.
- `backend_image_uri`가 persistent `dev` ECR의 `repository@sha256:<digest>`다.
- ASG는 min/desired/max `2/2/4`, Instance Refresh는 `100/200`, warm-up은 180초다.
- ALB traffic은 8080, health check는 `9091/actuator/health/readiness`다.
- RDS/Redis는 data private subnet과 전용 security group만 사용한다.
- 유료 리소스 수량이 NAT 1, ALB 1, EC2 2~4, RDS 1, Redis 1과 일치한다.

apply 후 `alb_dns_name`을 `api.kdt-travelplanner.protove.net`의 Cloudflare DNS-only CNAME target으로 수동 등록한다.

## 실험 종료와 비용 차단

`destroy`는 RDS 데이터와 Redis cache를 제거하며 final snapshot을 만들지 않는다. 합성 seed로 재생성할 수 있는지 확인하고 별도 승인을 받은 뒤 `dev-runtime` 디렉터리에서만 수행한다. 이후 NAT Gateway, ALB, ASG, RDS, Redis가 제거됐는지와 `dev` State의 VPC, ECR, profile image 리소스가 남아 있는지를 함께 확인한다.

## 장애 확인

인스턴스에는 SSH key와 public IP가 없다. SSM Session Manager로 접근하고 다음 위치를 확인한다.

- systemd: `travel-planner-backend.service`
- 컨테이너 환경 파일: `/etc/travel-planner/backend.env` (root 전용, 내용을 수집하지 않음)
- JSON 애플리케이션 로그: `/var/log/travel-planner`
- ALB readiness: `9091/actuator/health/readiness`

실패한 Instance Refresh는 자동 rollback하지 않는다. 실험 기록을 남긴 뒤 AWS Instance Refresh rollback 또는 이전 Launch Template version으로 새 refresh를 명시적으로 실행한다.
