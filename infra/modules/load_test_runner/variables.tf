variable "app_subnet_id" {
  type        = string
  description = "Private application subnet ID for the Load Runner EC2."
}

variable "aws_region" {
  type        = string
  description = "AWS region used by runtime SDK calls."
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
}

variable "evidence_bucket_name" {
  type        = string
  description = "S3 bucket name for raw load-test evidence (k6 output, run metadata, operations log)."
}

variable "evidence_retention_days" {
  type        = number
  description = <<-EOT
    Days before evidence objects expire. D-004 (Evidence S3 retention/KMS)
    was approved 2026-08-11: SSE-S3 (no KMS), 30-day retention. See
    aws-load-test-handoff/decisions/DECISION_LOG.md.
  EOT
  default     = 30

  validation {
    condition     = var.evidence_retention_days > 0
    error_message = "evidence_retention_days must be a positive number of days."
  }
}

variable "instance_type" {
  type        = string
  description = <<-EOT
    Load Runner EC2 instance type. D-001 was reversed by D-001-R1
    (aws-load-test-handoff/decisions/DECISION_LOG.md, 2026-08-11): no size is
    a permanent/required fixed value. t3.small is the default candidate;
    re-test with t3.medium only after Runner-side CPU/memory/network/OOM or
    dropped_iterations evidence (see scripts/loadtest/aws/run-k6-aws-scenario.sh's
    runner-stats.jsonl and validate-aws-run.py's runnerBottleneckSuspected)
    shows a bottleneck. t3.micro is a Smoke-only choice, not for Ramp/Baseline.
  EOT
  default     = "t3.small"
}

variable "k6_image_reference" {
  type        = string
  description = "Official DockerHub k6 image pinned to an exact digest (pulled once during bootstrap)."

  validation {
    condition     = can(regex("^grafana/k6:[0-9]+\\.[0-9]+\\.[0-9]+@sha256:[0-9a-f]{64}$", var.k6_image_reference))
    error_message = "k6_image_reference must be grafana/k6 with an exact X.Y.Z tag pinned by @sha256 digest."
  }
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in resource names."
}

variable "root_volume_size_gib" {
  type        = number
  description = "Encrypted gp3 root volume size for the Load Runner."
  default     = 20
}

variable "runner_security_group_id" {
  type        = string
  description = "Security group attached to the Load Runner EC2 (from the runtime_security module)."
}

variable "secrets_arns" {
  type        = list(string)
  description = "Secrets Manager ARNs the Runner may read for seed/cleanup DB credentials. Empty by default. D-001-R1 후속 (Seed/Cleanup 최소권한): must be a dedicated test-only Secret ARN, never the RDS master secret. Redis no longer uses a Secret at all — see redis_iam_auth_arns."
  default     = []
}

variable "redis_iam_auth_arns" {
  type        = list(string)
  description = "ARNs the Runner needs elasticache:Connect on for Redis RBAC IAM authentication: the load-test ElastiCache user ARN and the replication group ARN (both required together). Empty by default; the Seed/Cleanup Secret rework Issue wires actual ARNs in."
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to Load Runner resources."
  default     = {}
}
