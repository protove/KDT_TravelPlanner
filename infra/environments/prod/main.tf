locals {
  environment = "prod"
  bucket_name = "${var.project_name}-${local.environment}-profile-images-${var.aws_account_id}"
}

module "profile_image" {
  source = "../../modules/profile_image"

  acm_certificate_arn = var.acm_certificate_arn
  allowed_origins     = var.allowed_origins
  bucket_name         = local.bucket_name
  custom_domain_name  = var.custom_domain_name
  environment         = local.environment
}
