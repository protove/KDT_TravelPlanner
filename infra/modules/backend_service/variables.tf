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
  default     = "t3.small"
}

variable "instance_warmup_seconds" {
  type        = number
  description = "ASG default and Instance Refresh warm-up duration."
  default     = 180
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
