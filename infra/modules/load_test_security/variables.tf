variable "cache_security_group_id" {
  type        = string
  description = "Redis security group that accepts seed and cleanup traffic from the Load Runner."
}

variable "database_security_group_id" {
  type        = string
  description = "PostgreSQL security group that accepts seed and cleanup traffic from the Load Runner."
}

variable "eks_cluster_security_group_id" {
  type        = string
  description = "Optional EKS cluster security group allowed to reach the Runner-hosted Google mock on TCP/8080. Empty disables the rule for non-EKS load-test States."
  default     = ""
}

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
  description = "Tags applied to the Load Runner security group."
  default     = {}
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR used to restrict DNS egress to the Amazon-provided resolver."
}

variable "vpc_id" {
  type        = string
  description = "VPC that contains the Load Runner and dev runtime data services."
}
