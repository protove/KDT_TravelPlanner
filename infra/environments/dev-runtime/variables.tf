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
