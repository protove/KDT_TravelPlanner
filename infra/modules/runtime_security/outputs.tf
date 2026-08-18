output "alb_security_group_id" {
  description = "Public ALB security group ID."
  value       = aws_security_group.alb.id
}

output "backend_security_group_id" {
  description = "Private backend instance security group ID."
  value       = aws_security_group.backend.id
}

output "cache_security_group_id" {
  description = "Private Redis security group ID."
  value       = aws_security_group.cache.id
}

output "database_security_group_id" {
  description = "Private PostgreSQL security group ID."
  value       = aws_security_group.database.id
}

output "monitoring_security_group_id" {
  description = "Monitoring EC2 (Prometheus/Loki/Grafana) security group ID."
  value       = aws_security_group.monitoring.id
}
