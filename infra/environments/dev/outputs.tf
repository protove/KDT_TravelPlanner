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
