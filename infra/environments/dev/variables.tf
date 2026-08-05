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

variable "api_domain_name" {
  type        = string
  description = "Public API domain managed as a DNS-only record in Cloudflare."
  default     = "api.kdt-travelplanner.protove.net"

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", var.api_domain_name))
    error_message = "api_domain_name must be a valid lowercase DNS name."
  }
}

variable "app_subnet_cidrs" {
  type        = list(string)
  description = "Private application subnet CIDRs."
  default     = ["10.20.10.0/24", "10.20.11.0/24"]
}

variable "availability_zones" {
  type        = list(string)
  description = "Two Seoul availability zones used by the dev VPC."
  default     = ["ap-northeast-2a", "ap-northeast-2c"]
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

variable "frontend_custom_domain_enabled" {
  type        = bool
  description = "Enable the CloudFront custom alias only after the us-east-1 ACM certificate is issued."
  default     = false
}

variable "frontend_domain_name" {
  type        = string
  description = "Static frontend domain managed as a DNS-only record in Cloudflare."
  default     = "kdt-travelplanner.protove.net"

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", var.frontend_domain_name))
    error_message = "frontend_domain_name must be a valid lowercase DNS name."
  }
}

variable "frontend_html_cache_ttl_seconds" {
  type        = number
  description = "CloudFront TTL for frontend HTML and route documents."
  default     = 0

  validation {
    condition     = var.frontend_html_cache_ttl_seconds >= 0 && var.frontend_html_cache_ttl_seconds <= 3600
    error_message = "frontend_html_cache_ttl_seconds must be between 0 and 3600 seconds."
  }
}

variable "frontend_static_cache_ttl_seconds" {
  type        = number
  description = "CloudFront TTL for immutable Next.js assets."
  default     = 31536000

  validation {
    condition     = var.frontend_static_cache_ttl_seconds >= 86400 && var.frontend_static_cache_ttl_seconds <= 31536000
    error_message = "frontend_static_cache_ttl_seconds must be between one day and one year."
  }
}

variable "github_organization" {
  type        = string
  description = "GitHub organization trusted to publish the backend image through OIDC."
  default     = "protove"
}

variable "github_repository" {
  type        = string
  description = "GitHub repository whose dev Environment may publish the backend image."
  default     = "KDT_TravelPlanner"
}

variable "data_subnet_cidrs" {
  type        = list(string)
  description = "Isolated data subnet CIDRs."
  default     = ["10.20.20.0/24", "10.20.21.0/24"]
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

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "Public ALB and NAT Gateway subnet CIDRs."
  default     = ["10.20.0.0/24", "10.20.1.0/24"]
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the persistent dev VPC."
  default     = "10.20.0.0/16"
}
