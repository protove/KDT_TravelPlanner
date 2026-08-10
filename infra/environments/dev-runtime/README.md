# dev-runtime 운영 인계

`dev-runtime`은 부하·배포·복구 실험을 수행할 때만 생성하는 비용 발생 State다. VPC, subnet, ECR, API 인증서, 애플리케이션 secret 컨테이너와 기존 profile image 리소스는 `dev` State에 남고, 아래 리소스만 별도로 생성·제거한다.

- NAT Gateway 1개와 app private subnet 기본 경로
- Internet-facing ALB와 Target Group
- private EC2 ASG `2/2/4`, Launch Template, CPU 60% Target Tracking
- PostgreSQL 17 Single-AZ RDS와 Redis OSS 7.1 단일 노드
- Monitoring EC2의 Prometheus·Loki·Grafana와 Backend EC2의 Grafana Alloy

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

모니터링 이미지는 별도 빌드·ECR push 없이 NAT Gateway를 통해 공식 DockerHub에서 내려받는다. 기본 버전은 `infra/environments/dev-runtime/variables.tf`의 `monitoring_image_references`에 정의하며 `latest`와 tag 없는 참조는 허용하지 않는다. 버전을 변경하면 Monitoring EC2는 user data 변경에 따른 replacement가 발생하고, Alloy 버전 변경은 Launch Template 새 버전과 ASG Rolling Instance Refresh를 시작한다.

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
- Prometheus·Loki·Grafana·Alloy가 검토된 DockerHub 버전 태그를 사용하고 `latest`가 없다.
- ASG는 min/desired/max `2/2/4`, Instance Refresh는 `100/200`, warm-up은 180초다.
- Backend image digest가 바뀌면 Launch Template의 구체적인 새 버전과 ASG 변경이 plan에 나타나고, apply가 Rolling Instance Refresh를 시작한다. `$Latest` 문자열을 직접 사용하지 않는다.
- ALB traffic은 8080, health check는 `9091/actuator/health/readiness`다.
- Backend Alloy는 `0.0.0.0:12345`를 private host port로 publish하고, Monitoring SG에서만 접근 가능한 SG reference 규칙을 사용한다.
- Alloy job은 `Service=travel-planner-backend`, `Environment=dev`, `running` EC2를 Prometheus EC2 Service Discovery로 찾는다. `alloy:12345` 정적 target은 EC2 경로에 남아 있지 않아야 한다.
- RDS/Redis는 data private subnet과 전용 security group만 사용한다.
- 유료 리소스 수량이 NAT 1, ALB 1, EC2 2~4, RDS 1, Redis 1과 일치한다.
- Monitoring 이미지 변경 시 Monitoring EC2 replacement가 의도된 것인지 확인하고, apply 전에 필요한 Dashboard·Prometheus·Loki 증거를 외부에 보존한다.
- Prometheus/Loki/Grafana/대시보드 파일 hash 변경 시 `monitoring_config_revision`과 Monitoring EC2 replacement가 함께 나타나며, S3 object가 먼저 준비되는 dependency가 유지된다.

## 모니터링 변경 apply·refresh·rollback

계획 파일은 작업별로 고유한 이름을 사용한다. 기존 `tfplan` 파일을 덮어쓰지 않고, 아래 예시처럼 AWS profile과 `-chdir`를 항상 함께 지정한다.

```bash
AWS_PROFILE=kdt-travel-terraform \
terraform -chdir=infra/environments/dev-runtime \
  plan -var-file=terraform.tfvars \
  -out=dev-runtime-alloy-20260810.tfplan

AWS_PROFILE=kdt-travel-terraform \
terraform -chdir=infra/environments/dev-runtime \
  show dev-runtime-alloy-20260810.tfplan

AWS_PROFILE=kdt-travel-terraform \
terraform -chdir=infra/environments/dev-runtime \
  apply dev-runtime-alloy-20260810.tfplan
```

설정 revision만 확인하거나 drift를 조사할 때는 refresh-only plan을 사용한다. 이 명령은 상태를 바꾸지 않는다.

```bash
AWS_PROFILE=kdt-travel-terraform \
terraform -chdir=infra/environments/dev-runtime \
  plan -refresh-only -var-file=terraform.tfvars \
  -out=dev-runtime-alloy-refresh-20260810.tfplan
```

Alloy 설정·이미지 변경을 되돌릴 때는 이전에 검증한 Terraform 코드와 이미지 참조를 복원한 뒤 새 plan을 만들고, 그 plan에서 Backend ASG Instance Refresh와 Monitoring EC2 replacement 범위를 확인한다. 이전 plan을 재사용하거나 `-target`으로 일부만 적용하지 않는다. Backend EC2 교체 시 해당 인스턴스의 Docker named volume은 함께 사라질 수 있으므로, Loki에서 필요한 로그와 Grafana/Prometheus 증거를 먼저 보존한다.

apply 후에는 Prometheus API에서 `up{job="backend"}`와 `up{job="alloy"}`가 각각 Backend 인스턴스 수만큼 `1`인지, Alloy target의 `health`가 `up`인지 확인한다. `loki_source_file_files_active_total`, `loki_write_sent_entries_total`, `loki_write_dropped_entries_total`도 함께 확인하며 dropped entries는 `0`이어야 한다.

apply 후 `alb_dns_name`을 `api.kdt-travelplanner.protove.net`의 Cloudflare DNS-only CNAME target으로 수동 등록한다.

## 실험 종료와 비용 차단

`destroy`는 RDS 데이터와 Redis cache를 제거하며 final snapshot을 만들지 않는다. 합성 seed로 재생성할 수 있는지 확인하고 별도 승인을 받은 뒤 `dev-runtime` 디렉터리에서만 수행한다. 이후 NAT Gateway, ALB, ASG, RDS, Redis가 제거됐는지와 `dev` State의 VPC, ECR, profile image 리소스가 남아 있는지를 함께 확인한다.

## 장애 확인

인스턴스에는 SSH key와 public IP가 없다. SSM Session Manager로 접근하고 다음 위치를 확인한다.

- systemd: `travel-planner-backend.service`
- 컨테이너 환경 파일: `/etc/travel-planner/backend.env` (root 전용, 내용을 수집하지 않음)
- JSON 애플리케이션 로그: `/var/log/travel-planner`
- ALB readiness: `9091/actuator/health/readiness`

실패한 Instance Refresh는 자동 rollback하지 않는다. 현재 기본값은 이전 정상 `backend_image_uri` digest를 Terraform에 다시 입력하고 새 Launch Template version과 새 refresh를 명시적으로 실행하는 `MANUAL_BASELINE`이다. AWS 네이티브 rollback과 alarm 기반 자동화는 Desired Configuration과 동일한 오류 신호를 별도 검증하는 심화 범위로 둔다.
