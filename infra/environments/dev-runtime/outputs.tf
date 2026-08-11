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

output "load_runner_instance_id" {
  description = "Load Runner EC2 instance ID, the SSM target for AWS load-test orchestration."
  value       = module.load_test_runner.instance_id
}

output "load_runner_instance_type" {
  description = "Applied Load Runner EC2 instance type."
  value       = module.load_test_runner.instance_type
}

output "load_runner_source_commit_sha" {
  description = "Exact source commit bootstrapped on the Load Runner."
  value       = module.load_test_runner.source_commit_sha
}

output "load_test_evidence_bucket_name" {
  description = "S3 bucket name for raw AWS load-test evidence."
  value       = module.load_test_runner.evidence_bucket_name
}

output "load_test_evidence_operator_read_policy_arn" {
  description = "ARN of the unattached operator read-only policy for the load-test evidence prefix."
  value       = module.load_test_runner.evidence_operator_read_policy_arn
}

output "redis_primary_endpoint" {
  description = "Private Redis primary endpoint."
  value       = module.backend_data.redis_primary_endpoint
}

output "redis_load_test_user_name" {
  description = "Non-secret ElastiCache IAM RBAC username used by seed/cleanup."
  value       = module.backend_data.redis_load_test_user_name
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

output "target_group_arn" {
  description = "Backend ALB target group ARN."
  value       = module.backend_service.target_group_arn
}
