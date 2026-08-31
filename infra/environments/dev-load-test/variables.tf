variable "aws_account_id" {
  type        = string
  description = "Expected 12-digit AWS account ID."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  type        = string
  description = "AWS region for the dev Load Runner."
  default     = "ap-northeast-2"
}

variable "k6_image_reference" {
  type        = string
  description = "Official DockerHub k6 image pinned to the exact digest vetted by the Compose Gate."
  default     = "grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755"

  validation {
    condition     = can(regex("^grafana/k6:[0-9]+\\.[0-9]+\\.[0-9]+@sha256:[0-9a-f]{64}$", var.k6_image_reference))
    error_message = "k6_image_reference must be grafana/k6 with an exact X.Y.Z tag pinned by @sha256 digest."
  }
}

variable "load_runner_botocore_version" {
  type        = string
  description = "Pinned botocore version for the Redis IAM signer on the Runner."
  default     = "1.43.68"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.load_runner_botocore_version))
    error_message = "load_runner_botocore_version must be a pinned semantic version."
  }
}

variable "load_runner_instance_type" {
  type        = string
  description = "Ephemeral B-01 Load Runner EC2 type. Default t3.small; increase only after Runner-bottleneck evidence."
  default     = "t3.small"

  validation {
    condition     = can(regex("^t3\\.[a-z0-9]+$", var.load_runner_instance_type))
    error_message = "load_runner_instance_type must be a valid t3 family instance type."
  }
}

variable "load_runner_source_commit_sha" {
  type        = string
  description = "Exact merged commit SHA the ephemeral Runner must checkout."

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.load_runner_source_commit_sha))
    error_message = "load_runner_source_commit_sha must be an exact 40-character lowercase hexadecimal commit SHA."
  }
}

variable "persistent_state_key" {
  type        = string
  description = "Persistent dev Terraform State object key."
  default     = "dev/terraform.tfstate"
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in AWS resource names."
  default     = "kdt-travelplanner"
}

variable "runtime_state_key" {
  type        = string
  description = "Disposable runtime Terraform State object key consumed as the load-test target; use dev-runtime or dev-eks, never both at once."
  default     = "dev-runtime/terraform.tfstate"
}

variable "state_bucket" {
  type        = string
  description = "S3 bucket containing the persistent dev, disposable runtime and load-test Terraform States."
}

variable "test_db_secret_arn" {
  type        = string
  description = <<-EOT
    Secrets Manager ARN of the dedicated, least-privilege test-only DB Secret
    read by the Load Runner for seed and cleanup. It must never be the RDS
    master Secret. The Infra owner creates the DB role and Secret separately;
    this Root only grants the Runner permission to read the supplied ARN.
  EOT

  validation {
    condition = (
      startswith(
        var.test_db_secret_arn,
        "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}-dev/loadtest/db-"
        ) && can(regex(
          "^[A-Za-z0-9]{6}$",
          trimprefix(
            var.test_db_secret_arn,
            "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}-dev/loadtest/db-"
          )
      ))
    )
    error_message = "test_db_secret_arn must be the dedicated ${var.project_name}-dev/loadtest/db-* secret in aws_region and aws_account_id; RDS master secrets are forbidden."
  }
}
