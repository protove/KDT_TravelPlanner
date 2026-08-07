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
  vpc_id                             = "vpc-12345678"
}

run "backend_is_private_and_rolls_without_capacity_loss" {
  command = plan

  assert {
    condition = (
      !aws_launch_template.backend.network_interfaces[0].associate_public_ip_address &&
      aws_launch_template.backend.metadata_options[0].http_tokens == "required" &&
      aws_launch_template.backend.block_device_mappings[0].ebs[0].encrypted &&
      aws_launch_template.backend.block_device_mappings[0].ebs[0].volume_type == "gp3"
    )
    error_message = "Backend instances must have no public IP, require IMDSv2 and use encrypted gp3 storage."
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
    condition     = aws_autoscaling_policy.cpu.target_tracking_configuration[0].target_value == 60
    error_message = "CPU target tracking must use the agreed 60 percent target."
  }
}

run "tagged_image_is_rejected" {
  command = plan

  variables {
    backend_image_uri = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend:latest"
  }

  expect_failures = [var.backend_image_uri]
}
