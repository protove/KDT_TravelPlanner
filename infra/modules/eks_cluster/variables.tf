variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in resource names."
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private application subnet IDs for the control plane ENIs and managed node group. No public IPs are ever assigned."

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "subnet_ids must contain at least two subnets across separate availability zones."
  }
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

variable "endpoint_private_access" {
  type        = bool
  description = "Whether the cluster API server is reachable from inside the VPC. Nodes always use this path."
  default     = true
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
    known. No other exception mechanism is used for this constraint.
  EOT
  default     = ["0.0.0.0/0"]

  validation {
    condition     = length(var.public_access_cidrs) > 0
    error_message = "public_access_cidrs must contain at least one CIDR block when endpoint_public_access is enabled."
  }
}

variable "node_instance_types" {
  type        = list(string)
  description = "Managed node group EC2 instance types."
  default     = ["t3.medium"]

  validation {
    condition     = length(var.node_instance_types) > 0
    error_message = "node_instance_types must contain at least one instance type."
  }
}

variable "node_min_size" {
  type        = number
  description = "Minimum managed node group size."
  default     = 1

  validation {
    condition     = var.node_min_size >= 1
    error_message = "node_min_size must be at least 1."
  }
}

variable "node_max_size" {
  type        = number
  description = "Maximum managed node group size."
  default     = 1

  validation {
    condition     = var.node_max_size >= 1
    error_message = "node_max_size must be at least 1."
  }
}

variable "node_desired_size" {
  type        = number
  description = "Desired managed node group size."
  default     = 1

  validation {
    condition     = var.node_desired_size >= 1
    error_message = "node_desired_size must be at least 1."
  }
}

variable "cluster_log_retention_days" {
  type        = number
  description = "CloudWatch Logs retention for the control plane log group."
  default     = 30

  validation {
    condition     = var.cluster_log_retention_days >= 1
    error_message = "cluster_log_retention_days must be at least 1."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to EKS resources."
  default     = {}
}
