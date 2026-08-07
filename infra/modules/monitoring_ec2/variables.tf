variable "app_subnet_id" {
  type        = string
  description = "Private application subnet ID for the Monitoring EC2."
}

variable "aws_region" {
  type        = string
  description = "AWS region used by runtime SDK calls."
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
}

variable "instance_type" {
  type        = string
  description = "Monitoring EC2 instance type."
  default     = "t3.small"
}

variable "monitoring_bucket_name" {
  type        = string
  description = "S3 bucket name for uploaded Prometheus, Loki and Grafana config files."
}

variable "monitoring_endpoint_parameter_name" {
  type        = string
  description = "SSM Parameter Store path where the Monitoring EC2 private IP is published for Alloy log shipping."

  validation {
    condition     = can(regex("^/[a-zA-Z0-9_.\\-/]+$", var.monitoring_endpoint_parameter_name))
    error_message = "monitoring_endpoint_parameter_name must be an absolute SSM parameter path starting with /."
  }
}

variable "monitoring_security_group_id" {
  type        = string
  description = "Security group attached to the Monitoring EC2."
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in resource names."
}

variable "root_volume_size_gib" {
  type        = number
  description = "Encrypted gp3 root volume size for Prometheus/Loki/Grafana data."
  default     = 30
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to monitoring resources."
  default     = {}
}
