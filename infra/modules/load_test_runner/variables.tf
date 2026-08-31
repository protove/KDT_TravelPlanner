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

  validation {
    condition     = can(regex("^t3\\.[a-z0-9]+$", var.instance_type))
    error_message = "instance_type must be a t3 family instance type."
  }
}

variable "k6_image_reference" {
  type        = string
  description = "Official DockerHub k6 image pinned to an exact digest (pulled once during bootstrap)."

  validation {
    condition     = can(regex("^grafana/k6:[0-9]+\\.[0-9]+\\.[0-9]+@sha256:[0-9a-f]{64}$", var.k6_image_reference))
    error_message = "k6_image_reference must be grafana/k6 with an exact X.Y.Z tag pinned by @sha256 digest."
  }
}

variable "source_repository_url" {
  type        = string
  description = "Reviewed public repository URL containing the load-test scripts and k6 workloads."
  default     = "https://github.com/protove/KDT_TravelPlanner.git"

  validation {
    condition     = var.source_repository_url == "https://github.com/protove/KDT_TravelPlanner.git"
    error_message = "source_repository_url must remain the reviewed KDT_TravelPlanner repository."
  }
}

variable "source_commit_sha" {
  type        = string
  description = "Exact 40-hex commit SHA the Runner must checkout before executing a load test."

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_commit_sha))
    error_message = "source_commit_sha must be an exact 40-character lowercase hexadecimal commit SHA."
  }
}

variable "botocore_version" {
  type        = string
  description = "Exact botocore version installed for the Redis IAM SigV4 signer."
  default     = "1.43.68"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.botocore_version))
    error_message = "botocore_version must be a pinned semantic version."
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

variable "eks_observation_stack" {
  type        = string
  description = "Optional Stack tag for the single private EKS bastion used by the breakpoint observer. Empty disables EKS observation permissions."
  default     = ""

  validation {
    condition     = var.eks_observation_stack == "" || var.eks_observation_stack == "dev-eks"
    error_message = "eks_observation_stack must be empty or dev-eks."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to Load Runner resources."
  default     = {}
}
