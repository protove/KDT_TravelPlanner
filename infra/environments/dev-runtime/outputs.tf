output "alb_dns_name" {
  description = "Cloudflare DNS-only CNAME target for api.kdt-travelplanner.protove.net."
  value       = module.backend_service.alb_dns_name
}

output "autoscaling_group_name" {
  description = "Backend ASG name used by deployment and recovery experiments."
  value       = module.backend_service.autoscaling_group_name
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

output "target_group_arn" {
  description = "Backend ALB target group ARN."
  value       = module.backend_service.target_group_arn
}
