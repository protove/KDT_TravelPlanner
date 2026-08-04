output "profile_image_bucket_name" {
  description = "Value for PROFILE_IMAGE_STORAGE_BUCKET."
  value       = module.profile_image.bucket_name
}

output "profile_image_cloudfront_distribution_id" {
  description = "CloudFront distribution ID for profile images."
  value       = module.profile_image.cloudfront_distribution_id
}

output "profile_image_public_base_url" {
  description = "Value for PROFILE_IMAGE_PUBLIC_BASE_URL."
  value       = module.profile_image.public_base_url
}

output "profile_image_runtime_policy_arn" {
  description = "Unattached runtime policy ARN for the backend SSO permission set or runtime role."
  value       = module.profile_image.runtime_policy_arn
}

output "api_certificate_arn" {
  description = "Regional ACM certificate ARN. Use it only after Cloudflare DNS validation completes."
  value       = aws_acm_certificate.api.arn
}

output "api_certificate_dns_validation_records" {
  description = "CNAME records that an operator must add to Cloudflare with proxy disabled."
  value = {
    for option in aws_acm_certificate.api.domain_validation_options : option.domain_name => {
      name  = option.resource_record_name
      type  = option.resource_record_type
      value = option.resource_record_value
    }
  }
}

output "app_route_table_ids" {
  description = "Private application route tables used by the ephemeral NAT Gateway."
  value       = module.network.app_route_table_ids
}

output "app_subnet_ids" {
  description = "Private backend application subnet IDs."
  value       = module.network.app_subnet_ids
}

output "backend_application_secret_arn" {
  description = "Secret container ARN. The operator must create a value before starting dev-runtime."
  value       = aws_secretsmanager_secret.backend_application.arn
}

output "backend_ecr_repository_arn" {
  description = "Backend ECR repository ARN."
  value       = module.container_registry.repository_arn
}

output "backend_ecr_repository_url" {
  description = "Backend ECR repository URL. Runtime images must append an immutable digest."
  value       = module.container_registry.repository_url
}

output "data_subnet_ids" {
  description = "Isolated RDS and Redis subnet IDs."
  value       = module.network.data_subnet_ids
}

output "public_subnet_ids" {
  description = "Public ALB and NAT Gateway subnet IDs."
  value       = module.network.public_subnet_ids
}

output "vpc_id" {
  description = "Persistent dev VPC ID."
  value       = module.network.vpc_id
}

output "vpc_cidr" {
  description = "Persistent dev VPC CIDR."
  value       = module.network.vpc_cidr
}
