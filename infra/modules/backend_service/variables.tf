variable "alb_security_group_id" {
  type        = string
  description = "Security group attached to the public ALB."
}

variable "app_subnet_ids" {
  type        = list(string)
  description = "Private application subnet IDs for the backend ASG."

  validation {
    condition     = length(var.app_subnet_ids) == 2
    error_message = "app_subnet_ids must contain exactly two private subnets."
  }
}

variable "asg_desired_capacity" {
  type        = number
  description = "Desired backend instance count."
  default     = 2
}

variable "asg_max_size" {
  type        = number
  description = "Maximum backend instance count."
  default     = 4
}

variable "asg_min_size" {
  type        = number
  description = "Minimum backend instance count."
  default     = 2
}

variable "aws_region" {
  type        = string
  description = "AWS region used by runtime SDK calls."
}

variable "backend_application_secret_arn" {
  type        = string
  description = "Secrets Manager container populated by the operator with JWT, OAuth and Google credentials."
}

variable "backend_image_uri" {
  type        = string
  description = "Immutable ECR backend image URI including its sha256 digest."

  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.backend_image_uri))
    error_message = "backend_image_uri must be an ECR repository URI pinned with @sha256:<64 lowercase hexadecimal characters>."
  }
}

variable "backend_security_group_id" {
  type        = string
  description = "Security group attached to private backend instances."
}

variable "alloy_image_reference" {
  type        = string
  description = "Official DockerHub Grafana Alloy image pinned to an exact semantic version."

  validation {
    condition     = can(regex("^grafana/alloy:v[0-9]+\\.[0-9]+\\.[0-9]+$", var.alloy_image_reference))
    error_message = "alloy_image_reference must be grafana/alloy with an exact vX.Y.Z tag."
  }
}

variable "certificate_arn" {
  type        = string
  description = "Issued regional ACM certificate ARN for the API domain."
}

variable "database_address" {
  type        = string
  description = "RDS PostgreSQL hostname."
}

variable "database_master_secret_arn" {
  type        = string
  description = "RDS-managed database credential secret ARN."
}

variable "database_name" {
  type        = string
  description = "PostgreSQL database name."
}

variable "database_port" {
  type        = number
  description = "PostgreSQL port."
  default     = 5432
}

variable "ecr_repository_arn" {
  type        = string
  description = "Backend ECR repository ARN used by the instance pull policy."
}

variable "ecr_repository_url" {
  type        = string
  description = "Backend ECR repository URL without tag or digest."
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
}

variable "frontend_origin" {
  type        = string
  description = "Exact HTTPS frontend origin used by CORS and OAuth redirects."

  validation {
    condition     = can(regex("^https://[^/]+$", var.frontend_origin))
    error_message = "frontend_origin must be an exact HTTPS origin without a path."
  }
}

variable "google_oauth_redirect_uri" {
  type        = string
  description = "Google OAuth callback URI on the public API domain."
}

variable "instance_type" {
  type        = string
  description = "Backend EC2 instance type."
  default     = "t3.medium"
}

variable "health_check_grace_period_seconds" {
  type        = number
  description = "ASG ELB health-check grace period. Kept as an explicit comparison input; calibration may select a value from 60 through 300 seconds."
  default     = 300

  validation {
    condition = (
      var.health_check_grace_period_seconds >= 0 &&
      var.health_check_grace_period_seconds <= 600 &&
      var.health_check_grace_period_seconds == floor(var.health_check_grace_period_seconds)
    )
    error_message = "health_check_grace_period_seconds must be an integer from 0 through 600."
  }
}

variable "instance_warmup_seconds" {
  type        = number
  description = "ASG default and Instance Refresh warm-up duration."
  default     = 180
}

variable "monitoring_endpoint_parameter_name" {
  type        = string
  description = "SSM Parameter Store name holding the Monitoring EC2 private address for Alloy log shipping."

  validation {
    condition     = can(regex("^/[a-zA-Z0-9_.\\-/]+$", var.monitoring_endpoint_parameter_name))
    error_message = "monitoring_endpoint_parameter_name must be an absolute SSM parameter path starting with /."
  }
}

variable "naver_oauth_redirect_uri" {
  type        = string
  description = "Naver OAuth callback URI on the public API domain."
}

variable "profile_image_bucket_name" {
  type        = string
  description = "Existing profile image S3 bucket name."
}

variable "profile_image_public_base_url" {
  type        = string
  description = "Existing profile image CloudFront base URL."
}

variable "profile_image_runtime_policy_arn" {
  type        = string
  description = "Existing managed IAM policy that grants the backend profile image object access."
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in resource names."
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Two public subnets used by the ALB."

  validation {
    condition     = length(var.public_subnet_ids) == 2
    error_message = "public_subnet_ids must contain exactly two public subnets."
  }
}

variable "redis_auth_secret_arn" {
  type        = string
  description = "Secrets Manager ARN containing the Redis password."
}

variable "redis_port" {
  type        = number
  description = "Redis TLS port."
  default     = 6379
}

variable "redis_primary_endpoint" {
  type        = string
  description = "Redis primary endpoint hostname."
}

variable "root_volume_size_gib" {
  type        = number
  description = "Encrypted gp3 root volume size."
  default     = 20
}

variable "rollout_mode" {
  type        = string
  description = <<-EOT
    Immutable rollout contract selected for this plan. NORMAL and
    MANUAL_BASELINE preserve the 2/2/4, 100/200, scaling-enabled production
    baseline. EXPERIMENT and FAULT are the controlled recovery profiles with
    100/150, explicit checkpoints and scaling disabled.
  EOT
  default     = "NORMAL"

  validation {
    condition = contains([
      "NORMAL",
      "EXPERIMENT",
      "FAULT",
      "MANUAL_BASELINE",
    ], var.rollout_mode)
    error_message = "rollout_mode must be NORMAL, EXPERIMENT, FAULT, or MANUAL_BASELINE."
  }
}

variable "rollout_min_healthy_percentage" {
  type        = number
  description = "ASG Instance Refresh minimum healthy percentage for the selected rollout contract."
  default     = 100

  validation {
    condition = (
      var.rollout_min_healthy_percentage >= 0 &&
      var.rollout_min_healthy_percentage <= 100 &&
      var.rollout_min_healthy_percentage == floor(var.rollout_min_healthy_percentage)
    )
    error_message = "rollout_min_healthy_percentage must be an integer from 0 through 100."
  }
}

variable "rollout_max_healthy_percentage" {
  type        = number
  description = "ASG Instance Refresh maximum healthy percentage for the selected rollout contract."
  default     = 200

  validation {
    condition = (
      var.rollout_max_healthy_percentage >= 100 &&
      var.rollout_max_healthy_percentage <= 200 &&
      var.rollout_max_healthy_percentage == floor(var.rollout_max_healthy_percentage)
    )
    error_message = "rollout_max_healthy_percentage must be an integer from 100 through 200."
  }
}

variable "rollout_checkpoint_percentages" {
  type        = list(number)
  description = "Ordered ASG Instance Refresh checkpoints. Normal/manual baseline must be empty; experiments use [50] or [50, 100]."
  default     = []

  validation {
    condition = (
      length(var.rollout_checkpoint_percentages) <= 2 &&
      alltrue([
        for percentage in var.rollout_checkpoint_percentages : (
          percentage > 0 &&
          percentage <= 100 &&
          percentage == floor(percentage)
        )
      ]) &&
      length(distinct(var.rollout_checkpoint_percentages)) == length(var.rollout_checkpoint_percentages)
    )
    error_message = "rollout_checkpoint_percentages must contain at most two distinct integer percentages from 1 through 100."
  }
}

variable "rollout_checkpoint_delay_seconds" {
  type        = number
  description = "Optional delay after each Instance Refresh checkpoint."
  default     = 60

  validation {
    condition = (
      var.rollout_checkpoint_delay_seconds >= 0 &&
      var.rollout_checkpoint_delay_seconds == floor(var.rollout_checkpoint_delay_seconds)
    )
    error_message = "rollout_checkpoint_delay_seconds must be a non-negative integer."
  }
}

variable "rollout_scaling_policy_enabled" {
  type        = bool
  description = "Whether the CPU target-tracking policy is attached to the backend ASG."
  default     = true
}

variable "rollout_revision" {
  type        = string
  description = <<-EOT
    Operator-supplied rollout revision marker bound into the Launch Template
    instance tags. Changing only this value creates a new numbered Launch
    Template version, so an EXPERIMENT rollout performs a real Instance
    Refresh even when the backend image digest is unchanged.
  EOT
  default     = "baseline"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{1,64}$", var.rollout_revision))
    error_message = "rollout_revision must be 1 to 64 characters of letters, digits, dot, underscore, or hyphen."
  }
}

variable "rollout_normal_backend_image_uri" {
  type        = string
  description = "Exact normal Backend ECR digest used as the MANUAL_BASELINE restore target."
  default     = null
  nullable    = true

  validation {
    condition = (
      var.rollout_normal_backend_image_uri == null ? true : can(regex(
        "^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$",
        var.rollout_normal_backend_image_uri
      ))
    )
    error_message = "rollout_normal_backend_image_uri must be an ECR image URI pinned with @sha256 when supplied."
  }
}

variable "rollout_fault_backend_image_uri" {
  type        = string
  description = "Exact fault Backend ECR digest used only by the FAULT rollout contract."
  default     = null
  nullable    = true

  validation {
    condition = (
      var.rollout_fault_backend_image_uri == null ? true : can(regex(
        "^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$",
        var.rollout_fault_backend_image_uri
      ))
    )
    error_message = "rollout_fault_backend_image_uri must be an ECR image URI pinned with @sha256 when supplied."
  }
}

variable "rollout_restore_backend_image_uri" {
  type        = string
  description = "Exact previously healthy Backend ECR digest required by MANUAL_BASELINE."
  default     = null
  nullable    = true

  validation {
    condition = (
      var.rollout_restore_backend_image_uri == null ? true : can(regex(
        "^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$",
        var.rollout_restore_backend_image_uri
      ))
    )
    error_message = "rollout_restore_backend_image_uri must be an ECR image URI pinned with @sha256 when supplied."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to backend resources."
  default     = {}
}

variable "target_cpu_utilization" {
  type        = number
  description = "ASG target tracking CPU percentage."
  default     = 60
}

variable "vpc_id" {
  type        = string
  description = "VPC that contains the backend runtime."
}
