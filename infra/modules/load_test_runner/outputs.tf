output "instance_id" {
  description = "Load Runner EC2 instance ID (SSM target for orchestration)."
  value       = aws_instance.load_runner.id
}

output "private_ip" {
  description = "Load Runner private IP."
  value       = aws_instance.load_runner.private_ip
}

output "instance_type" {
  description = "Load Runner EC2 instance type applied to the ephemeral runtime."
  value       = aws_instance.load_runner.instance_type
}

output "source_commit_sha" {
  description = "Exact load-test repository commit configured for the Runner bootstrap."
  value       = var.source_commit_sha
}

output "evidence_bucket_arn" {
  description = "Evidence S3 bucket ARN."
  value       = aws_s3_bucket.evidence.arn
}

output "evidence_bucket_name" {
  description = "Evidence S3 bucket name."
  value       = aws_s3_bucket.evidence.id
}

output "iam_role_arn" {
  description = "Load Runner IAM role ARN, for wiring additional least-privilege policies (e.g. seed/cleanup adapter) without modifying this module."
  value       = aws_iam_role.load_runner.arn
}

output "iam_role_name" {
  description = "Load Runner IAM role name."
  value       = aws_iam_role.load_runner.name
}

output "evidence_operator_read_policy_arn" {
  description = "ARN of the unattached least-privilege operator read-only policy for the load-test evidence prefix. Not attached automatically; connect it to an SSO Permission Set or Role as documented in infra/README.md."
  value       = aws_iam_policy.evidence_operator_read.arn
}
