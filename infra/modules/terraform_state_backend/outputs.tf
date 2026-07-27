output "bucket_arn" {
  description = "ARN of the Terraform state bucket."
  value       = aws_s3_bucket.this.arn
}

output "bucket_name" {
  description = "Name of the Terraform state bucket."
  value       = aws_s3_bucket.this.bucket
}

output "state_access_policy_json" {
  description = "Least-privilege IAM policy document for day-to-day Terraform state access."
  value       = data.aws_iam_policy_document.state_access.json
}
