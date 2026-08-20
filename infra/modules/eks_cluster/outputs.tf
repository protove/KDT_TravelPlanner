output "cluster_name" {
  description = "EKS cluster name, the kubectl/SSM target for SCRUM-11 verification."
  value       = aws_eks_cluster.this.name
}

output "cluster_arn" {
  description = "EKS cluster ARN."
  value       = aws_eks_cluster.this.arn
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded cluster CA certificate for kubeconfig generation."
  value       = aws_eks_cluster.this.certificate_authority[0].data
}

output "cluster_security_group_id" {
  description = "Security group EKS creates and manages for control-plane-to-node communication."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "cluster_version" {
  description = "Applied EKS Kubernetes minor version."
  value       = aws_eks_cluster.this.version
}

output "oidc_provider_arn" {
  description = "Cluster IRSA OIDC provider ARN. SCRUM-11 trusts this when creating workload roles."
  value       = aws_iam_openid_connect_provider.cluster.arn
}

output "oidc_provider_url" {
  description = "Cluster IRSA OIDC issuer URL, without the https:// prefix as required by IAM trust policies."
  value       = replace(aws_iam_openid_connect_provider.cluster.url, "https://", "")
}

output "node_group_name" {
  description = "Managed node group name."
  value       = aws_eks_node_group.this.node_group_name
}

output "node_group_arn" {
  description = "Managed node group ARN."
  value       = aws_eks_node_group.this.arn
}

output "node_group_status" {
  description = "Managed node group status, for operator plan/apply verification."
  value       = aws_eks_node_group.this.status
}

output "node_role_arn" {
  description = "EC2 instance role ARN attached to managed node group instances."
  value       = aws_iam_role.node.arn
}

output "secrets_kms_key_arn" {
  description = "Dedicated KMS key ARN used for EKS Kubernetes Secrets envelope encryption."
  value       = aws_kms_key.eks_secrets.arn
}
