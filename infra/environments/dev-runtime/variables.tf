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
  description = "AWS region for the dev runtime."
  default     = "ap-northeast-2"
}

variable "backend_image_uri" {
  type        = string
  description = "Backend ECR image pinned by sha256 digest."

  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.backend_image_uri))
    error_message = "backend_image_uri must be an ECR image pinned with @sha256."
  }
}

variable "k6_image_reference" {
  type        = string
  description = "Official DockerHub k6 image pinned to an exact digest, matching the version already vetted by the Compose Gate (load-tests/gate-profile.json)."
  default     = "grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755"

  validation {
    condition     = can(regex("^grafana/k6:[0-9]+\\.[0-9]+\\.[0-9]+@sha256:[0-9a-f]{64}$", var.k6_image_reference))
    error_message = "k6_image_reference must be grafana/k6 with an exact X.Y.Z tag pinned by @sha256 digest."
  }
}

variable "monitoring_image_references" {
  type = object({
    prometheus = string
    loki       = string
    grafana    = string
    alloy      = string
  })
  description = "Official DockerHub monitoring images pinned to reviewed semantic versions."
  default = {
    prometheus = "prom/prometheus:v3.13.1"
    loki       = "grafana/loki:3.7.2"
    grafana    = "grafana/grafana:13.1.0"
    alloy      = "grafana/alloy:v1.16.1"
  }

  validation {
    condition = alltrue([
      can(regex("^prom/prometheus:v[0-9]+\\.[0-9]+\\.[0-9]+$", var.monitoring_image_references.prometheus)),
      can(regex("^grafana/loki:[0-9]+\\.[0-9]+\\.[0-9]+$", var.monitoring_image_references.loki)),
      can(regex("^grafana/grafana:[0-9]+\\.[0-9]+\\.[0-9]+$", var.monitoring_image_references.grafana)),
      can(regex("^grafana/alloy:v[0-9]+\\.[0-9]+\\.[0-9]+$", var.monitoring_image_references.alloy)),
    ])
    error_message = "monitoring_image_references must use the official DockerHub repositories with exact semantic version tags; latest and tagless references are not allowed."
  }
}

variable "persistent_state_bucket" {
  type        = string
  description = "S3 bucket containing the persistent dev Terraform State."
}

variable "persistent_state_key" {
  type        = string
  description = "Persistent dev Terraform State object key."
  default     = "dev/terraform.tfstate"
}

variable "postgres_engine_version" {
  type        = string
  description = "Exact PostgreSQL 17 version returned for ap-northeast-2 before the operator plan."

  validation {
    condition     = can(regex("^17\\.[0-9]+$", var.postgres_engine_version))
    error_message = "postgres_engine_version must pin an exact PostgreSQL 17 patch version."
  }
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in AWS resource names."
  default     = "kdt-travelplanner"
}

variable "test_db_secret_arn" {
  type        = string
  description = <<-EOT
    Secrets Manager ARN of the dedicated, least-privilege test-only DB Secret
    the load-test Runner reads to seed/cleanup B-01 data, JSON shape
    {"username": "...", "password": "..."}. D-001-R1 후속 "Seed/Cleanup
    최소권한" (aws-load-test-handoff/decisions/DECISION_LOG.md): this must
    never be the RDS master secret (module.backend_data.database_master_secret_arn).
    The Infra owner creates the actual DB role and Secret (console or
    approved IaC, per aws-load-test-handoff/README.md) and supplies its ARN
    here — this module only wires the ARN in, it does not create the role.
  EOT

  validation {
    condition     = can(regex("^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:", var.test_db_secret_arn))
    error_message = "test_db_secret_arn must be a Secrets Manager secret ARN."
  }
}
