output "load_runner_instance_id" {
  description = "Load Runner EC2 instance ID, the SSM target for AWS load-test orchestration."
  value       = module.load_test_runner.instance_id
}

output "load_runner_instance_type" {
  description = "Applied Load Runner EC2 instance type."
  value       = module.load_test_runner.instance_type
}

output "load_runner_source_commit_sha" {
  description = "Exact source commit bootstrapped on the Load Runner."
  value       = module.load_test_runner.source_commit_sha
}

output "load_runner_source_delivery_prefix" {
  description = "Private run-scoped S3 prefix used for exact source delivery."
  value       = module.load_test_runner.source_delivery_prefix
}

output "load_runner_base_readiness_path" {
  description = "Runner-local cloud-init base readiness receipt path."
  value       = module.load_test_runner.base_readiness_path
}

output "load_runner_full_readiness_path" {
  description = "Runner-local full source/image/mock readiness receipt path."
  value       = module.load_test_runner.full_readiness_path
}

output "load_runner_k6_image_reference" {
  description = "Digest-pinned k6 image for the staged Runner bootstrap."
  value       = module.load_test_runner.k6_image_reference
}

output "load_runner_google_mock_image_reference" {
  description = "Digest-pinned private mock image for the staged Runner bootstrap."
  value       = module.load_test_runner.google_mock_image_reference
}

output "load_test_evidence_bucket_name" {
  description = "S3 bucket name for raw AWS load-test evidence."
  value       = module.load_test_runner.evidence_bucket_name
}

output "load_test_evidence_operator_read_policy_arn" {
  description = "ARN of the unattached operator read-only policy for the load-test evidence prefix."
  value       = module.load_test_runner.evidence_operator_read_policy_arn
}

output "load_test_security_group_id" {
  description = "Security group attached to the private Load Runner EC2."
  value       = module.load_test_security.security_group_id
}

output "target_runtime_state_key" {
  description = "Disposable runtime State key consumed by this Load Runner deployment (dev-runtime or dev-eks)."
  value       = var.runtime_state_key
}

output "google_api_mock_fqdn" {
  description = "Private Runner-hosted Google API mock FQDN for the dev-eks disposable render (null for dev-runtime)."
  value       = one(aws_route53_record.google_api_mock[*].fqdn)
}
