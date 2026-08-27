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

variable "grafana_anonymous_viewer_enabled" {
  type        = bool
  description = "Temporary action-time Grafana anonymous Viewer access through an SSM loopback tunnel; default-off."
  default     = false
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

variable "backend_health_check_grace_period_seconds" {
  type        = number
  description = "EC2 ASG ELB health-check grace period; retain the availability seed until final Acceptance proves a shorter value across replacement variance."
  default     = 300

  validation {
    condition = (
      var.backend_health_check_grace_period_seconds >= 0 &&
      var.backend_health_check_grace_period_seconds <= 600 &&
      var.backend_health_check_grace_period_seconds == floor(var.backend_health_check_grace_period_seconds)
    )
    error_message = "backend_health_check_grace_period_seconds must be an integer from 0 through 600."
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
