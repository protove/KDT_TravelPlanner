output "alb_dns_name" {
  description = "Cloudflare DNS-only CNAME target for api.kdt-travelplanner.protove.net."
  value       = module.backend_service.alb_dns_name
}

output "alb_arn" {
  description = "Backend ALB ARN used to resolve the LoadBalancer CloudWatch dimension."
  value       = module.backend_service.alb_arn
}

output "autoscaling_group_name" {
  description = "Backend ASG name used by deployment and recovery experiments."
  value       = module.backend_service.autoscaling_group_name
}

output "monitoring_instance_id" {
  description = "Monitoring EC2 instance ID used for Grafana SSM tunneling."
  value       = module.monitoring_ec2.instance_id
}

output "database_address" {
  description = "Private RDS hostname."
  value       = module.backend_data.database_address
}

output "launch_template_id" {
  description = "Backend Launch Template ID used by Instance Refresh."
  value       = module.backend_service.launch_template_id
}

output "redis_primary_endpoint" {
  description = "Private Redis primary endpoint."
  value       = module.backend_data.redis_primary_endpoint
}

output "redis_load_test_user_name" {
  description = "Non-secret ElastiCache IAM RBAC username used by seed/cleanup."
  value       = module.backend_data.redis_load_test_user_name
}

output "redis_load_test_user_arn" {
  description = "ElastiCache IAM RBAC user ARN consumed by the separately applied dev-load-test State."
  value       = module.backend_data.redis_load_test_user_arn
}

output "redis_replication_group_arn" {
  description = "ElastiCache replication group ARN consumed by the separately applied dev-load-test State."
  value       = module.backend_data.redis_replication_group_arn
}

output "redis_replication_group_id" {
  description = "ElastiCache replication group ID."
  value       = module.backend_data.redis_replication_group_id
}

output "redis_member_cluster_ids" {
  description = "ElastiCache member cluster IDs for CloudWatch dimension resolution."
  value       = module.backend_data.redis_member_cluster_ids
}

output "database_name" {
  description = "RDS database name used by seed/cleanup."
  value       = module.backend_data.database_name
}

output "database_port" {
  description = "RDS database port used by seed/cleanup."
  value       = module.backend_data.database_port
}

output "database_identifier" {
  description = "RDS DB instance identifier used by CloudWatch dimensions."
  value       = module.backend_data.database_identifier
}

output "database_security_group_id" {
  description = "PostgreSQL security group ID used by the separately applied dev-load-test State."
  value       = module.runtime_security.database_security_group_id
}

output "cache_security_group_id" {
  description = "Redis security group ID used by the separately applied dev-load-test State."
  value       = module.runtime_security.cache_security_group_id
}

output "target_group_arn" {
  description = "Backend ALB target group ARN."
  value       = module.backend_service.target_group_arn
}

output "backend_rollout_contract" {
  description = "Terraform-emitted rollout contract consumed by validate-rollout-plan.py before an approved recovery apply."
  value       = module.backend_service.rollout_contract
}

output "backend_restoration_state_contract" {
  description = "Terraform-emitted restoration contract for the post-recovery drift check; the AWS read-back exporter promotes status to verified."
  value       = module.backend_service.restoration_state_contract
}

output "backend_launch_template_latest_version" {
  description = "Concrete numbered Launch Template version the ASG references, recorded in recovery evidence."
  value       = module.backend_service.launch_template_latest_version
}
