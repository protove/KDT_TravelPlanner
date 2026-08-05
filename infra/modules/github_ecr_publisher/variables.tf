variable "ecr_repository_arn" {
  type        = string
  description = "ARN of the only ECR repository that the GitHub publisher may access."

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ecr:[a-z0-9-]+:[0-9]{12}:repository/[a-z0-9][a-z0-9._/-]*$", var.ecr_repository_arn))
    error_message = "ecr_repository_arn must be a valid private ECR repository ARN."
  }
}

variable "environment" {
  type        = string
  description = "Deployment environment name used by the IAM role and GitHub Environment subject."

  validation {
    condition     = can(regex("^[a-z0-9]+(?:[-_][a-z0-9]+)*$", var.environment))
    error_message = "environment must use lowercase letters, numbers, hyphens or underscores."
  }
}

variable "github_organization" {
  type        = string
  description = "GitHub organization that owns the trusted repository."

  validation {
    condition     = can(regex("^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$", var.github_organization))
    error_message = "github_organization must be a valid GitHub organization name."
  }
}

variable "github_repository" {
  type        = string
  description = "GitHub repository whose dev Environment may assume the publisher role."

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be a valid GitHub repository name."
  }
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in IAM resource names."
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to GitHub OIDC IAM resources."
  default     = {}
}
