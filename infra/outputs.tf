output "bucket_name" {
  value = aws_s3_bucket.profile_images.bucket
}

output "bucket_region" {
  value = "ap-northeast-2"
}

# PROFILE_IMAGE_PUBLIC_BASE_URL에 넣을 값
output "cdn_domain_name" {
  value       = aws_cloudfront_distribution.profile_images_cdn.domain_name
  description = "이 값 앞에 https:// 붙여서 PROFILE_IMAGE_PUBLIC_BASE_URL로 사용"
}

output "access_key_id" {
  value = aws_iam_access_key.backend_uploader_key.id
}

output "secret_access_key" {
  value     = aws_iam_access_key.backend_uploader_key.secret
  sensitive = true
}
