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
    is not decided yet; this default (30) mirrors the retention candidate in
    aws-load-test-handoff/contracts/SECURITY_AND_RETENTION_POLICY.md and must
    be revisited once D-004 is approved.
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
    Load Runner EC2 instance type. D-001 (Runner instance type/budget) is not
    decided yet; this default is a placeholder pending infra owner approval,
    not a sized recommendation for the actual B-01 arrival-rate.
  EOT
  default     = "t3.medium"
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
  description = "Secrets Manager ARNs the Runner may read for seed/cleanup credentials (e.g. database, Redis). Empty by default; the seed/cleanup adapter Issue wires actual ARNs in."
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to Load Runner resources."
  default     = {}
}
