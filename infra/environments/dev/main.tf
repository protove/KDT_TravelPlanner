locals {
  environment          = "dev"
  bucket_name          = "${var.project_name}-${local.environment}-profile-images-${var.aws_account_id}"
  frontend_bucket_name = "${var.project_name}-${local.environment}-frontend-${var.aws_account_id}"
  common_tags = {
    Environment = local.environment
    Phase       = "ec2-baseline"
    Project     = var.project_name
  }
}

module "static_frontend" {
  source = "../../modules/static_frontend"

  acm_certificate_arn      = var.frontend_custom_domain_enabled ? aws_acm_certificate.frontend.arn : null
  bucket_name              = local.frontend_bucket_name
  custom_domain_name       = var.frontend_custom_domain_enabled ? var.frontend_domain_name : null
  environment              = local.environment
  html_cache_ttl_seconds   = var.frontend_html_cache_ttl_seconds
  project_name             = var.project_name
  static_cache_ttl_seconds = var.frontend_static_cache_ttl_seconds
  tags                     = local.common_tags
}

module "profile_image" {
  source = "../../modules/profile_image"

  acm_certificate_arn = var.acm_certificate_arn
  allowed_origins     = var.allowed_origins
  bucket_name         = local.bucket_name
  custom_domain_name  = var.custom_domain_name
  environment         = local.environment
}

module "network" {
  source = "../../modules/network"

  app_subnet_cidrs    = var.app_subnet_cidrs
  availability_zones  = var.availability_zones
  data_subnet_cidrs   = var.data_subnet_cidrs
  environment         = local.environment
  project_name        = var.project_name
  public_subnet_cidrs = var.public_subnet_cidrs
  tags                = local.common_tags
  vpc_cidr            = var.vpc_cidr
}

module "container_registry" {
  source = "../../modules/container_registry"

  environment  = local.environment
  project_name = var.project_name
  tags         = local.common_tags
}

module "github_ecr_publisher" {
  source = "../../modules/github_ecr_publisher"

  ecr_repository_arn  = module.container_registry.repository_arn
  environment         = local.environment
  github_organization = var.github_organization
  github_repository   = var.github_repository
  project_name        = var.project_name
  tags                = local.common_tags
}

module "github_frontend_deployer" {
  source = "../../modules/github_frontend_deployer"

  cloudfront_distribution_arn = module.static_frontend.cloudfront_distribution_arn
  environment                 = local.environment
  frontend_bucket_arn         = module.static_frontend.bucket_arn
  github_oidc_provider_arn    = module.github_ecr_publisher.github_oidc_provider_arn
  github_organization         = var.github_organization
  github_repository           = var.github_repository
  project_name                = var.project_name
  tags                        = local.common_tags
}

resource "aws_acm_certificate" "api" {
  domain_name       = var.api_domain_name
  validation_method = "DNS"
  tags              = local.common_tags

  lifecycle {
    create_before_destroy = true
    prevent_destroy       = true
  }
}

resource "aws_acm_certificate" "frontend" {
  provider = aws.us_east_1

  domain_name       = var.frontend_domain_name
  validation_method = "DNS"
  tags              = local.common_tags

  lifecycle {
    create_before_destroy = true
    prevent_destroy       = true
  }
}

resource "aws_secretsmanager_secret" "backend_application" {
  name                    = "${var.project_name}/${local.environment}/backend/application"
  description             = "Operator-managed JWT, OAuth and Google credentials for the backend runtime"
  recovery_window_in_days = 7
  tags                    = local.common_tags

  lifecycle {
    prevent_destroy = true
  }
}
