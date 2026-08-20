output "security_group_id" {
  description = "SSM-only k6 Load Runner security group ID."
  value       = aws_security_group.load_runner.id
}
