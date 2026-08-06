output "alb_arn" {
  description = "Backend ALB ARN."
  value       = aws_lb.this.arn
}

output "alb_dns_name" {
  description = "Cloudflare DNS-only CNAME target for the API domain."
  value       = aws_lb.this.dns_name
}

output "autoscaling_group_name" {
  description = "Backend Auto Scaling Group name."
  value       = aws_autoscaling_group.backend.name
}

output "launch_template_id" {
  description = "Backend Launch Template ID."
  value       = aws_launch_template.backend.id
}

output "target_group_arn" {
  description = "Backend target group ARN."
  value       = aws_lb_target_group.backend.arn
}
