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

output "launch_template_latest_version" {
  description = "Concrete numbered Launch Template version referenced by the ASG."
  value       = aws_launch_template.backend.latest_version
}

output "rollout_contract" {
  description = "Resolved, digest-bound rollout contract for operator evidence and plan review."
  value = {
    mode                     = var.rollout_mode
    minHealthyPercentage     = var.rollout_min_healthy_percentage
    maxHealthyPercentage     = var.rollout_max_healthy_percentage
    checkpointPercentages    = var.rollout_checkpoint_percentages
    checkpointDelaySeconds   = var.rollout_checkpoint_delay_seconds
    scalingPolicyEnabled     = var.rollout_scaling_policy_enabled
    normalBackendImageUri    = var.rollout_normal_backend_image_uri
    faultBackendImageUri     = var.rollout_fault_backend_image_uri
    restoreBackendImageUri   = var.rollout_restore_backend_image_uri
    desiredCapacity          = var.asg_desired_capacity
    minSize                  = var.asg_min_size
    maxSize                  = var.asg_max_size
    autoRollback             = false
    launchTemplateVersionRef = tostring(aws_launch_template.backend.latest_version)
  }
}

output "restoration_state_contract" {
  description = "Sanitized contract consumed by the recovery evidence adapter; AWS read-back must promote status to verified."
  value = {
    mode                     = var.rollout_mode
    status                   = "planned"
    desiredCapacity          = var.asg_desired_capacity
    minSize                  = var.asg_min_size
    maxSize                  = var.asg_max_size
    launchTemplateVersion    = tostring(aws_launch_template.backend.latest_version)
    launchTemplateVersionRef = tostring(aws_launch_template.backend.latest_version)
    normalImageDigest        = var.rollout_normal_backend_image_uri
    capacityRestored         = false
    scalingPolicyEnabled     = var.rollout_scaling_policy_enabled
    autoRollback             = false
    manualBaselineRequired   = var.rollout_mode == "MANUAL_BASELINE"
  }
}

output "target_group_arn" {
  description = "Backend target group ARN."
  value       = aws_lb_target_group.backend.arn
}
