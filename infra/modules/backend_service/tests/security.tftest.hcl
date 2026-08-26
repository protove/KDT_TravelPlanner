mock_provider "aws" {
  override_during = plan

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"ec2.amazonaws.com\"}}]}"
    }
  }

  mock_data "aws_ssm_parameter" {
    defaults = {
      value = "ami-0123456789abcdef0"
    }
  }

  mock_resource "aws_lb" {
    defaults = {
      arn      = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/test/123"
      dns_name = "test.ap-northeast-2.elb.amazonaws.com"
    }
  }

  mock_resource "aws_lb_target_group" {
    defaults = {
      arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:targetgroup/test/123"
    }
  }

  mock_resource "aws_launch_template" {
    defaults = {
      id             = "lt-0123456789abcdef0"
      latest_version = 7
    }
  }
}

variables {
  alb_security_group_id              = "sg-alb"
  alloy_image_reference              = "grafana/alloy:v1.16.1"
  app_subnet_ids                     = ["subnet-app-a", "subnet-app-c"]
  aws_region                         = "ap-northeast-2"
  backend_application_secret_arn     = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:app"
  backend_image_uri                  = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  backend_security_group_id          = "sg-backend"
  certificate_arn                    = "arn:aws:acm:ap-northeast-2:123456789012:certificate/12345678-1234-1234-1234-123456789012"
  database_address                   = "database.internal"
  database_master_secret_arn         = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:rds"
  database_name                      = "travel_diary_dev"
  ecr_repository_arn                 = "arn:aws:ecr:ap-northeast-2:123456789012:repository/kdt-travelplanner-dev-backend"
  ecr_repository_url                 = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend"
  environment                        = "dev"
  frontend_origin                    = "https://kdt-travelplanner.protove.net"
  google_oauth_redirect_uri          = "https://api.kdt-travelplanner.protove.net/api/v1/auth/oauth2/google/callback"
  monitoring_endpoint_parameter_name = "/kdt-travelplanner/dev/monitoring-endpoint"
  naver_oauth_redirect_uri           = "https://api.kdt-travelplanner.protove.net/api/v1/auth/oauth2/naver/callback"
  profile_image_bucket_name          = "kdt-travelplanner-dev-profile-images-123456789012"
  profile_image_public_base_url      = "https://images.example.com"
  profile_image_runtime_policy_arn   = "arn:aws:iam::123456789012:policy/profile-image"
  project_name                       = "kdt-travelplanner"
  public_subnet_ids                  = ["subnet-public-a", "subnet-public-c"]
  redis_auth_secret_arn              = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:redis"
  redis_primary_endpoint             = "redis.internal"
  rollout_normal_backend_image_uri   = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  vpc_id                             = "vpc-12345678"
}

run "backend_is_private_and_rolls_without_capacity_loss" {
  command = plan

  assert {
    condition = (
      !aws_launch_template.backend.network_interfaces[0].associate_public_ip_address &&
      aws_launch_template.backend.metadata_options[0].http_tokens == "required" &&
      aws_launch_template.backend.block_device_mappings[0].ebs[0].encrypted &&
      aws_launch_template.backend.block_device_mappings[0].ebs[0].volume_type == "gp3" &&
      strcontains(base64decode(aws_launch_template.backend.user_data), var.alloy_image_reference) &&
      strcontains(base64decode(aws_launch_template.backend.user_data), "--publish 12345:12345") &&
      strcontains(base64decode(aws_launch_template.backend.user_data), "--volume travel-planner-alloy-data:/var/lib/alloy/data") &&
      strcontains(base64decode(aws_launch_template.backend.user_data), "--server.http.listen-addr=0.0.0.0:12345") &&
      strcontains(base64decode(aws_launch_template.backend.user_data), "--storage.path=/var/lib/alloy/data") &&
      aws_launch_template.backend.tag_specifications[0].tags["Version"] == var.alloy_image_reference &&
      !strcontains(base64decode(aws_launch_template.backend.user_data), "grafana/alloy:latest")
    )
    error_message = "Backend instances must have no public IP, require IMDSv2, use encrypted gp3 storage and expose Alloy metrics with persistent position storage."
  }

  assert {
    condition = (
      aws_lb_target_group.backend.port == 8080 &&
      aws_lb_target_group.backend.health_check[0].port == "9091" &&
      aws_lb_target_group.backend.health_check[0].path == "/actuator/health/readiness"
    )
    error_message = "ALB traffic and readiness health ports must remain separate."
  }

  assert {
    condition = (
      aws_autoscaling_group.backend.min_size == 2 &&
      aws_autoscaling_group.backend.desired_capacity == 2 &&
      aws_autoscaling_group.backend.max_size == 4 &&
      aws_launch_template.backend.instance_type == "t3.medium" &&
      aws_autoscaling_group.backend.health_check_grace_period == 300 &&
      aws_autoscaling_group.backend.enabled_metrics == toset([
        "GroupDesiredCapacity",
        "GroupInServiceInstances",
        "GroupPendingInstances",
      ]) &&
      aws_autoscaling_group.backend.metrics_granularity == "1Minute" &&
      aws_autoscaling_group.backend.instance_refresh[0].preferences[0].min_healthy_percentage == 100 &&
      aws_autoscaling_group.backend.instance_refresh[0].preferences[0].max_healthy_percentage == 200 &&
      !aws_autoscaling_group.backend.instance_refresh[0].preferences[0].auto_rollback
    )
    error_message = "The EC2 baseline must use 2-to-4 capacity and manual 100/200 Instance Refresh."
  }

  assert {
    condition = (
      aws_autoscaling_group.backend.launch_template[0].version ==
      tostring(aws_launch_template.backend.latest_version)
    )
    error_message = "The ASG must reference the concrete Launch Template version so image changes trigger Instance Refresh."
  }

  assert {
    condition     = aws_autoscaling_policy.cpu[0].target_tracking_configuration[0].target_value == 60
    error_message = "CPU target tracking must use the agreed 60 percent target."
  }
}

run "experiment_uses_checkpoint_contract_and_disables_scaling" {
  command = plan

  variables {
    rollout_mode                   = "EXPERIMENT"
    rollout_max_healthy_percentage = 150
    rollout_checkpoint_percentages = [50]
    rollout_scaling_policy_enabled = false
  }

  assert {
    condition = (
      aws_autoscaling_group.backend.instance_refresh[0].preferences[0].min_healthy_percentage == 100 &&
      aws_autoscaling_group.backend.instance_refresh[0].preferences[0].max_healthy_percentage == 150 &&
      tolist(aws_autoscaling_group.backend.instance_refresh[0].preferences[0].checkpoint_percentages) == tolist([50]) &&
      length(aws_autoscaling_policy.cpu) == 0
    )
    error_message = "Experiment rollouts must use 100/150, checkpoint [50], and no CPU target-tracking policy."
  }
}

run "fault_requires_distinct_pinned_digest" {
  command = plan

  variables {
    rollout_mode                    = "FAULT"
    rollout_max_healthy_percentage  = 150
    rollout_checkpoint_percentages  = [50, 100]
    rollout_scaling_policy_enabled  = false
    rollout_fault_backend_image_uri = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    backend_image_uri               = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }

  assert {
    condition = (
      tolist(aws_autoscaling_group.backend.instance_refresh[0].preferences[0].checkpoint_percentages) == tolist([50, 100]) &&
      length(aws_autoscaling_policy.cpu) == 0
    )
    error_message = "Fault rollouts must bind the exact fault digest and remain scaling-disabled."
  }
}

run "manual_baseline_requires_exact_restore_digest" {
  command = plan

  variables {
    rollout_mode                      = "MANUAL_BASELINE"
    rollout_restore_backend_image_uri = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  assert {
    condition = (
      aws_autoscaling_group.backend.instance_refresh[0].preferences[0].min_healthy_percentage == 100 &&
      aws_autoscaling_group.backend.instance_refresh[0].preferences[0].max_healthy_percentage == 200 &&
      length(aws_autoscaling_group.backend.instance_refresh[0].preferences[0].checkpoint_percentages) == 0 &&
      length(aws_autoscaling_policy.cpu) == 1
    )
    error_message = "MANUAL_BASELINE must create a new normal-digest rollout with the default 100/200 policy."
  }
}

run "experiment_rejects_production_refresh_shape" {
  command = plan

  variables {
    rollout_mode                   = "EXPERIMENT"
    rollout_max_healthy_percentage = 200
    rollout_checkpoint_percentages = []
    rollout_scaling_policy_enabled = true
  }

  expect_failures = [aws_autoscaling_group.backend]
}

run "manual_baseline_rejects_mismatched_restore_digest" {
  command = plan

  variables {
    rollout_mode                      = "MANUAL_BASELINE"
    rollout_restore_backend_image_uri = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }

  expect_failures = [aws_autoscaling_group.backend]
}

run "tagged_image_is_rejected" {
  command = plan

  variables {
    backend_image_uri = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend:latest"
  }

  expect_failures = [var.backend_image_uri]
}

run "latest_alloy_image_is_rejected" {
  command = plan

  variables {
    alloy_image_reference = "grafana/alloy:latest"
  }

  expect_failures = [var.alloy_image_reference]
}

run "rollout_revision_is_bound_into_launch_template_instance_tags" {
  command = plan

  variables {
    rollout_mode                   = "EXPERIMENT"
    rollout_max_healthy_percentage = 150
    rollout_checkpoint_percentages = [50]
    rollout_scaling_policy_enabled = false
    rollout_revision               = "r01-test-1"
  }

  assert {
    condition = (
      aws_launch_template.backend.tag_specifications[0].tags["RolloutRevision"] == "r01-test-1"
    )
    error_message = "rollout_revision must be bound into the Launch Template instance tags so changing it alone creates a new numbered version."
  }
}

run "malformed_rollout_revision_is_rejected" {
  command = plan

  variables {
    rollout_revision = "not allowed!"
  }

  expect_failures = [var.rollout_revision]
}
