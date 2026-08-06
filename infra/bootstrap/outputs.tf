output "state_access_policy_json" {
  description = "Least-privilege policy JSON to attach to the day-to-day Terraform SSO role."
  value       = module.terraform_state_backend.state_access_policy_json
}

output "state_bucket_arn" {
  description = "ARN of the Terraform state bucket."
  value       = module.terraform_state_backend.bucket_arn
}

output "state_bucket_name" {
  description = "Name of the Terraform state bucket."
  value       = module.terraform_state_backend.bucket_name
}
