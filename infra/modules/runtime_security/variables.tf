variable "environment" {
  type        = string
  description = "Deployment environment name."
}

variable "project_name" {
  type        = string
  description = "Lowercase project identifier used in resource names."
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to security groups."
  default     = {}
}

variable "vpc_id" {
  type        = string
  description = "VPC that contains the ALB, backend and data resources."
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR used to restrict DNS egress to the Amazon-provided resolver."
}
