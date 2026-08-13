output "instance_id" {
  description = "Monitoring EC2 instance ID."
  value       = aws_instance.monitoring.id
}

output "monitoring_endpoint_parameter_arn" {
  description = "SSM Parameter ARN holding the Monitoring EC2 private IP."
  value       = aws_ssm_parameter.monitoring_endpoint.arn
}

output "monitoring_endpoint_parameter_name" {
  description = "SSM Parameter name holding the Monitoring EC2 private IP."
  value       = aws_ssm_parameter.monitoring_endpoint.name
}

output "monitoring_config_revision" {
  description = "Hash of the Prometheus, Loki and Grafana configuration uploaded to S3."
  value       = local.monitoring_config_revision
}

output "private_ip" {
  description = "Monitoring EC2 private IP (Prometheus/Loki/Grafana host)."
  value       = aws_instance.monitoring.private_ip
}
