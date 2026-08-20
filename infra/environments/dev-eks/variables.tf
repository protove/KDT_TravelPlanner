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
  description = "AWS region for the dev EKS cluster."
  default     = "ap-northeast-2"
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

variable "state_bucket" {
  type        = string
  description = "S3 bucket containing the persistent dev Terraform State."
}

variable "persistent_state_key" {
  type        = string
  description = "Persistent dev Terraform State object key."
  default     = "dev/terraform.tfstate"
}

variable "kubernetes_version" {
  type        = string
  description = "EKS control plane Kubernetes minor version."
  default     = "1.31"

  validation {
    condition     = can(regex("^1\\.[0-9]{2}$", var.kubernetes_version))
    error_message = "kubernetes_version must be an EKS-supported 1.NN minor version string."
  }
}

variable "endpoint_public_access" {
  type        = bool
  description = "Whether the cluster API server is reachable over the public internet, for kubectl verification convenience."
  default     = true
}

variable "public_access_cidrs" {
  type        = list(string)
  description = <<-EOT
    CIDR blocks allowed through the public API endpoint. Temporarily open to
    the internet (0.0.0.0/0) to unblock kubectl verification before the
    team's fixed IP/VPN range is confirmed; narrow this once that range is
    known.
  EOT
  default     = ["0.0.0.0/0"]
}

variable "node_instance_types" {
  type        = list(string)
  description = "Managed node group EC2 instance types."
  default     = ["t3.medium"]
}

variable "node_min_size" {
  type        = number
  description = "Minimum managed node group size."
  default     = 1
}

variable "node_max_size" {
  type        = number
  description = "Maximum managed node group size."
  default     = 1
}

variable "node_desired_size" {
  type        = number
  description = "Desired managed node group size."
  default     = 1
}
