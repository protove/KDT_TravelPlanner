locals {
  environment     = "dev"
  frontend_origin = "https://kdt-travelplanner.protove.net"
  api_origin      = "https://api.kdt-travelplanner.protove.net"
  common_tags = {
    Environment = local.environment
    Phase       = "ec2-baseline"
    Project     = var.project_name
  }
}

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

  alb_security_group_id            = module.runtime_security.alb_security_group_id
  app_subnet_ids                   = data.terraform_remote_state.persistent.outputs.app_subnet_ids
  asg_desired_capacity             = 2
  asg_max_size                     = 4
  asg_min_size                     = 2
  aws_region                       = var.aws_region
  backend_application_secret_arn   = data.terraform_remote_state.persistent.outputs.backend_application_secret_arn
  backend_image_uri                = var.backend_image_uri
  backend_security_group_id        = module.runtime_security.backend_security_group_id
  certificate_arn                  = data.terraform_remote_state.persistent.outputs.api_certificate_arn
  database_address                 = module.backend_data.database_address
  database_master_secret_arn       = module.backend_data.database_master_secret_arn
  database_name                    = module.backend_data.database_name
  database_port                    = module.backend_data.database_port
  ecr_repository_arn               = data.terraform_remote_state.persistent.outputs.backend_ecr_repository_arn
  ecr_repository_url               = data.terraform_remote_state.persistent.outputs.backend_ecr_repository_url
  environment                      = local.environment
  frontend_origin                  = local.frontend_origin
  google_oauth_redirect_uri        = "${local.api_origin}/api/v1/auth/oauth2/google/callback"
  instance_type                    = "t3.small"
  instance_warmup_seconds          = 180
  naver_oauth_redirect_uri         = "${local.api_origin}/api/v1/auth/oauth2/naver/callback"
  profile_image_bucket_name        = data.terraform_remote_state.persistent.outputs.profile_image_bucket_name
  profile_image_public_base_url    = data.terraform_remote_state.persistent.outputs.profile_image_public_base_url
  profile_image_runtime_policy_arn = data.terraform_remote_state.persistent.outputs.profile_image_runtime_policy_arn
  project_name                     = var.project_name
  public_subnet_ids                = data.terraform_remote_state.persistent.outputs.public_subnet_ids
  redis_auth_secret_arn            = module.backend_data.redis_auth_secret_arn
  redis_port                       = module.backend_data.redis_port
  redis_primary_endpoint           = module.backend_data.redis_primary_endpoint
  tags                             = local.common_tags
  target_cpu_utilization           = 60
  vpc_id                           = data.terraform_remote_state.persistent.outputs.vpc_id

  depends_on = [
    aws_route.app_default,
    terraform_data.backend_image_contract,
  ]
}
