locals {
  environment                        = "dev"
  frontend_origin                    = "https://kdt-travelplanner.protove.net"
  api_origin                         = "https://api.kdt-travelplanner.protove.net"
  monitoring_endpoint_parameter_name = "/kdt-travelplanner/dev/monitoring-endpoint"
  common_tags = {
    Environment = local.environment
    Phase       = "ec2-baseline"
    Project     = var.project_name
  }
}

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "persistent" {
  backend = "s3"

  config = {
    bucket       = var.persistent_state_bucket
    key          = var.persistent_state_key
    region       = var.aws_region
    use_lockfile = true
    encrypt      = true
  }
}

resource "terraform_data" "backend_image_contract" {
  input = var.backend_image_uri

  lifecycle {
    precondition {
      condition     = startswith(var.backend_image_uri, "${data.terraform_remote_state.persistent.outputs.backend_ecr_repository_url}@sha256:")
      error_message = "backend_image_uri must use the ECR repository created by the persistent dev State."
    }
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${var.project_name}-${local.environment}-nat" })
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = data.terraform_remote_state.persistent.outputs.public_subnet_ids[0]
  tags          = merge(local.common_tags, { Name = "${var.project_name}-${local.environment}-nat" })
}

resource "aws_route" "app_default" {
  for_each = toset(data.terraform_remote_state.persistent.outputs.app_route_table_ids)

  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
  route_table_id         = each.value
}

module "runtime_security" {
  source = "../../modules/runtime_security"

  environment  = local.environment
  project_name = var.project_name
  tags         = local.common_tags
  vpc_cidr     = data.terraform_remote_state.persistent.outputs.vpc_cidr
  vpc_id       = data.terraform_remote_state.persistent.outputs.vpc_id
}

module "monitoring_ec2" {
  source = "../../modules/monitoring_ec2"

  app_subnet_id                      = data.terraform_remote_state.persistent.outputs.app_subnet_ids[0]
  aws_region                         = var.aws_region
  environment                        = local.environment
  prometheus_image_reference         = var.monitoring_image_references.prometheus
  loki_image_reference               = var.monitoring_image_references.loki
  grafana_image_reference            = var.monitoring_image_references.grafana
  monitoring_bucket_name             = "${var.project_name}-${local.environment}-monitoring-config-${data.aws_caller_identity.current.account_id}"
  monitoring_endpoint_parameter_name = local.monitoring_endpoint_parameter_name
  monitoring_security_group_id       = module.runtime_security.monitoring_security_group_id
  project_name                       = var.project_name
  tags                               = local.common_tags

  depends_on = [
    aws_route.app_default,
  ]
}

module "load_test_runner" {
  source = "../../modules/load_test_runner"

  app_subnet_id            = data.terraform_remote_state.persistent.outputs.app_subnet_ids[0]
  aws_region               = var.aws_region
  environment              = local.environment
  evidence_bucket_name     = "${var.project_name}-${local.environment}-load-test-evidence-${data.aws_caller_identity.current.account_id}"
  instance_type            = var.load_runner_instance_type
  botocore_version         = var.load_runner_botocore_version
  k6_image_reference       = var.k6_image_reference
  source_commit_sha        = var.load_runner_source_commit_sha
  project_name             = var.project_name
  runner_security_group_id = module.runtime_security.load_runner_security_group_id
  # D-001-R1 후속 "Seed/Cleanup 최소권한" (aws-load-test-handoff/decisions/
  # DECISION_LOG.md): the Runner no longer reads the RDS master secret or
  # the backend's shared Redis AUTH secret (#247's original wiring). DB
  # access is a dedicated test-only Secret supplied by the Infra owner
  # (var.test_db_secret_arn); Redis access is ElastiCache RBAC + IAM auth
  # (no Secret at all — see module.backend_data's redis_load_test_user_arn/
  # redis_replication_group_arn outputs).
  secrets_arns = [
    var.test_db_secret_arn,
  ]
  redis_iam_auth_arns = [
    module.backend_data.redis_load_test_user_arn,
    module.backend_data.redis_replication_group_arn,
  ]
  tags = local.common_tags

  depends_on = [
    aws_route.app_default,
  ]
}

module "backend_data" {
  source = "../../modules/backend_data"

  cache_node_type            = "cache.t4g.micro"
  cache_security_group_id    = module.runtime_security.cache_security_group_id
  data_subnet_ids            = data.terraform_remote_state.persistent.outputs.data_subnet_ids
  database_name              = "travel_diary_dev"
  database_security_group_id = module.runtime_security.database_security_group_id
  database_username          = "travel_planner"
  db_instance_class          = "db.t4g.micro"
  environment                = local.environment
  postgres_engine_version    = var.postgres_engine_version
  project_name               = var.project_name
  redis_engine_version       = "7.1"
  tags                       = local.common_tags
}

module "backend_service" {
  source = "../../modules/backend_service"

  alb_security_group_id              = module.runtime_security.alb_security_group_id
  app_subnet_ids                     = data.terraform_remote_state.persistent.outputs.app_subnet_ids
  asg_desired_capacity               = 2
  asg_max_size                       = 4
  asg_min_size                       = 2
  aws_region                         = var.aws_region
  backend_application_secret_arn     = data.terraform_remote_state.persistent.outputs.backend_application_secret_arn
  backend_image_uri                  = var.backend_image_uri
  backend_security_group_id          = module.runtime_security.backend_security_group_id
  certificate_arn                    = data.terraform_remote_state.persistent.outputs.api_certificate_arn
  database_address                   = module.backend_data.database_address
  database_master_secret_arn         = module.backend_data.database_master_secret_arn
  database_name                      = module.backend_data.database_name
  database_port                      = module.backend_data.database_port
  ecr_repository_arn                 = data.terraform_remote_state.persistent.outputs.backend_ecr_repository_arn
  ecr_repository_url                 = data.terraform_remote_state.persistent.outputs.backend_ecr_repository_url
  environment                        = local.environment
  frontend_origin                    = local.frontend_origin
  google_oauth_redirect_uri          = "${local.api_origin}/api/v1/auth/oauth2/google/callback"
  instance_type                      = "t3.small"
  instance_warmup_seconds            = 180
  alloy_image_reference              = var.monitoring_image_references.alloy
  monitoring_endpoint_parameter_name = module.monitoring_ec2.monitoring_endpoint_parameter_name
  naver_oauth_redirect_uri           = "${local.api_origin}/api/v1/auth/oauth2/naver/callback"
  profile_image_bucket_name          = data.terraform_remote_state.persistent.outputs.profile_image_bucket_name
  profile_image_public_base_url      = data.terraform_remote_state.persistent.outputs.profile_image_public_base_url
  profile_image_runtime_policy_arn   = data.terraform_remote_state.persistent.outputs.profile_image_runtime_policy_arn
  project_name                       = var.project_name
  public_subnet_ids                  = data.terraform_remote_state.persistent.outputs.public_subnet_ids
  redis_auth_secret_arn              = module.backend_data.redis_auth_secret_arn
  redis_port                         = module.backend_data.redis_port
  redis_primary_endpoint             = module.backend_data.redis_primary_endpoint
  rollout_mode                       = var.backend_rollout_mode
  rollout_min_healthy_percentage     = var.backend_rollout_min_healthy_percentage
  rollout_max_healthy_percentage     = var.backend_rollout_max_healthy_percentage
  rollout_checkpoint_percentages     = var.backend_rollout_checkpoint_percentages
  rollout_checkpoint_delay_seconds   = var.backend_rollout_checkpoint_delay_seconds
  rollout_scaling_policy_enabled     = var.backend_rollout_scaling_policy_enabled
  rollout_normal_backend_image_uri   = coalesce(var.backend_rollout_normal_image_uri, var.backend_image_uri)
  rollout_fault_backend_image_uri    = var.backend_rollout_fault_image_uri
  rollout_restore_backend_image_uri  = var.backend_rollout_restore_image_uri
  tags                               = local.common_tags
  target_cpu_utilization             = 60
  vpc_id                             = data.terraform_remote_state.persistent.outputs.vpc_id

  depends_on = [
    aws_route.app_default,
  ]
}
