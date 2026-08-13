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

variable "load_runner_botocore_version" {
  type        = string
  description = "Pinned botocore version for the Redis IAM signer on the Runner."
  default     = "1.43.68"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.load_runner_botocore_version))
    error_message = "load_runner_botocore_version must be a pinned semantic version."
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

variable "backend_rollout_mode" {
  type        = string
  description = <<-EOT
    Backend rollout contract for this saved plan. NORMAL is the default
    2/2/4, 100/200, scaling-enabled baseline. EXPERIMENT/FAULT require the
    explicit 100/150 checkpoint contract. MANUAL_BASELINE requires an exact
    previously healthy restore digest.
  EOT
  default     = "NORMAL"

  validation {
    condition = contains([
      "NORMAL",
      "EXPERIMENT",
      "FAULT",
      "MANUAL_BASELINE",
    ], var.backend_rollout_mode)
    error_message = "backend_rollout_mode must be NORMAL, EXPERIMENT, FAULT, or MANUAL_BASELINE."
  }
}

variable "backend_rollout_min_healthy_percentage" {
  type        = number
  description = "Instance Refresh minimum healthy percentage for the backend rollout contract."
  default     = 100

  validation {
    condition = (
      var.backend_rollout_min_healthy_percentage >= 0 &&
      var.backend_rollout_min_healthy_percentage <= 100 &&
      var.backend_rollout_min_healthy_percentage == floor(var.backend_rollout_min_healthy_percentage)
    )
    error_message = "backend_rollout_min_healthy_percentage must be an integer from 0 through 100."
  }
}

variable "backend_rollout_max_healthy_percentage" {
  type        = number
  description = "Instance Refresh maximum healthy percentage for the backend rollout contract."
  default     = 200

  validation {
    condition = (
      var.backend_rollout_max_healthy_percentage >= 100 &&
      var.backend_rollout_max_healthy_percentage <= 200 &&
      var.backend_rollout_max_healthy_percentage == floor(var.backend_rollout_max_healthy_percentage)
    )
    error_message = "backend_rollout_max_healthy_percentage must be an integer from 100 through 200."
  }
}

variable "backend_rollout_checkpoint_percentages" {
  type        = list(number)
  description = "Ordered Instance Refresh checkpoints. EXPERIMENT/FAULT use [50] or [50, 100]."
  default     = []

  validation {
    condition = (
      length(var.backend_rollout_checkpoint_percentages) <= 2 &&
      alltrue([
        for percentage in var.backend_rollout_checkpoint_percentages : (
          percentage > 0 &&
          percentage <= 100 &&
          percentage == floor(percentage)
        )
      ]) &&
      length(distinct(var.backend_rollout_checkpoint_percentages)) == length(var.backend_rollout_checkpoint_percentages)
    )
    error_message = "backend_rollout_checkpoint_percentages must contain at most two distinct integer percentages from 1 through 100."
  }
}

variable "backend_rollout_checkpoint_delay_seconds" {
  type        = number
  description = "Optional delay after each Instance Refresh checkpoint."
  default     = 60

  validation {
    condition = (
      var.backend_rollout_checkpoint_delay_seconds >= 0 &&
      var.backend_rollout_checkpoint_delay_seconds == floor(var.backend_rollout_checkpoint_delay_seconds)
    )
    error_message = "backend_rollout_checkpoint_delay_seconds must be a non-negative integer."
  }
}

variable "backend_rollout_scaling_policy_enabled" {
  type        = bool
  description = "Whether backend CPU target tracking is enabled for this plan."
  default     = true
}

variable "backend_rollout_revision" {
  type        = string
  description = "Rollout revision marker bound into the backend Launch Template; changing it alone forces a new numbered Launch Template version and a real Instance Refresh."
  default     = "baseline"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{1,64}$", var.backend_rollout_revision))
    error_message = "backend_rollout_revision must be 1 to 64 characters of letters, digits, dot, underscore, or hyphen."
  }
}

variable "backend_rollout_normal_image_uri" {
  type        = string
  description = "Previously healthy Backend ECR digest used for normal and MANUAL_BASELINE contracts."
  default     = null
  nullable    = true

  validation {
    condition = (
      var.backend_rollout_normal_image_uri == null ? true : can(regex(
        "^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$",
        var.backend_rollout_normal_image_uri
      ))
    )
    error_message = "backend_rollout_normal_image_uri must be an ECR image URI pinned with @sha256 when supplied."
  }
}

variable "backend_rollout_fault_image_uri" {
  type        = string
  description = "Fault Backend ECR digest used only for a FAULT contract."
  default     = null
  nullable    = true

  validation {
    condition = (
      var.backend_rollout_fault_image_uri == null ? true : can(regex(
        "^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$",
        var.backend_rollout_fault_image_uri
      ))
    )
    error_message = "backend_rollout_fault_image_uri must be an ECR image URI pinned with @sha256 when supplied."
  }
}

variable "backend_rollout_restore_image_uri" {
  type        = string
  description = "Previously healthy digest required by MANUAL_BASELINE restore plans."
  default     = null
  nullable    = true

  validation {
    condition = (
      var.backend_rollout_restore_image_uri == null ? true : can(regex(
        "^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$",
        var.backend_rollout_restore_image_uri
      ))
    )
    error_message = "backend_rollout_restore_image_uri must be an ECR image URI pinned with @sha256 when supplied."
  }
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
