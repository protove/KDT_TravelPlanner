output "cluster_name" {
  description = "EKS cluster name, the kubectl/SSM target for SCRUM-11 verification."
  value       = module.eks_cluster.cluster_name
}

output "cluster_arn" {
  description = "EKS cluster ARN."
  value       = module.eks_cluster.cluster_arn
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks_cluster.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded cluster CA certificate for kubeconfig generation."
  value       = module.eks_cluster.cluster_certificate_authority_data
}

output "cluster_security_group_id" {
  description = "Security group EKS creates and manages for control-plane-to-node communication."
  value       = module.eks_cluster.cluster_security_group_id
}

output "cluster_version" {
  description = "Applied EKS Kubernetes minor version."
  value       = module.eks_cluster.cluster_version
}

output "oidc_provider_arn" {
  description = "Cluster IRSA OIDC provider ARN. SCRUM-11 trusts this when creating workload roles."
  value       = module.eks_cluster.oidc_provider_arn
}

output "oidc_provider_url" {
  description = "Cluster IRSA OIDC issuer URL, without the https:// prefix as required by IAM trust policies."
  value       = module.eks_cluster.oidc_provider_url
}

output "node_group_name" {
  description = "Managed node group name."
  value       = module.eks_cluster.node_group_name
}

output "node_group_status" {
  description = "Managed node group status, for operator plan/apply verification."
  value       = module.eks_cluster.node_group_status
}

output "secrets_kms_key_arn" {
  description = "Dedicated KMS key ARN used for EKS Kubernetes Secrets envelope encryption."
  value       = module.eks_cluster.secrets_kms_key_arn
}

output "admin_access_entry_principal_arns" {
  description = "IAM principal ARNs granted cluster-admin via Access Entries, for operator verification."
  value       = module.eks_cluster.admin_access_entry_principal_arns
}

output "bastion_instance_id" {
  description = "SSM Session Manager target for the SSM-only EKS verification bastion (no public IP, no SSH)."
  value       = aws_instance.bastion.id
}

output "target_persistent_state_key" {
  description = "Persistent dev Terraform State key this EKS deployment reads app_subnet_ids from."
  value       = var.persistent_state_key
}
