variable "acm_certificate_arn" {
  type        = string
  description = "Optional us-east-1 ACM certificate ARN for the image custom domain."
  default     = null
  nullable    = true
}

variable "allowed_origins" {
  type        = set(string)
  description = "Exact frontend origins allowed to upload profile images."
  default     = ["http://localhost:3000"]
}

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
  description = "AWS region for regional resources."
  default     = "ap-northeast-2"
}

variable "custom_domain_name" {
  type        = string
  description = "Optional CloudFront image custom domain."
  default     = null
  nullable    = true
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in AWS resource names."
  default     = "kdt-travelplanner"

  validation {
    condition     = can(regex("^[a-z0-9]+(?:-[a-z0-9]+)*$", var.project_name))
    error_message = "project_name must use lowercase letters, numbers, and single hyphens."
  }
}
