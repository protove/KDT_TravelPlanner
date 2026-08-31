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

variable "google_mock_image_reference" {
  type        = string
  description = "Digest-pinned linux/amd64 nginx-unprivileged image for the isolated Runner-hosted Google API mock."
  default     = "nginxinc/nginx-unprivileged:1.27.1-alpine3.20-perl@sha256:86b08eb3082f1f796f0ce1ef75a1c356a116fafc5f88754924fba2286fbd0221"

  validation {
    condition     = can(regex("^nginxinc/nginx-unprivileged:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$", var.google_mock_image_reference))
    error_message = "google_mock_image_reference must be nginxinc/nginx-unprivileged with an exact digest."
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
  description = "Ephemeral B-01 Load Runner EC2 type. Historical t3.* values remain valid; SCRUM-80 uses c6i.2xlarge with one c6i.4xlarge repair."
  default     = "t3.small"

  validation {
    condition     = can(regex("^(t3\\.[a-z0-9]+|c6i\\.(2xlarge|4xlarge))$", var.load_runner_instance_type))
    error_message = "load_runner_instance_type must be a t3 family type or c6i.2xlarge/c6i.4xlarge."
  }
}

variable "load_runner_root_volume_size_gib" {
  type        = number
  description = "Encrypted gp3 root volume size for the disposable Load Runner."
  default     = 20

  validation {
    condition     = var.load_runner_root_volume_size_gib >= 20 && var.load_runner_root_volume_size_gib <= 200
    error_message = "load_runner_root_volume_size_gib must be between 20 and 200 GiB."
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
