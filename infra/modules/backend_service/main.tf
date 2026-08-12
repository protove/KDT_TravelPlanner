locals {
  name = "${var.project_name}-${var.environment}"

  # Keep the rollout shape explicit in Terraform so an experiment cannot
  # accidentally inherit the production capacity/scaling contract. The
  # launch template always receives a digest-pinned image; the mode-specific
  # checks below additionally bind that image to the approved normal/fault
  # artifact.
  rollout_is_experiment = contains(["EXPERIMENT", "FAULT"], var.rollout_mode)

  rollout_profile_shape_valid = (
    var.rollout_mode == "NORMAL" ? (
      var.rollout_min_healthy_percentage == 100 &&
      var.rollout_max_healthy_percentage == 200 &&
      length(var.rollout_checkpoint_percentages) == 0 &&
      var.rollout_scaling_policy_enabled
      ) : var.rollout_mode == "MANUAL_BASELINE" ? (
      var.rollout_min_healthy_percentage == 100 &&
      var.rollout_max_healthy_percentage == 200 &&
      length(var.rollout_checkpoint_percentages) == 0 &&
      var.rollout_scaling_policy_enabled
      ) : local.rollout_is_experiment ? (
      var.rollout_min_healthy_percentage == 100 &&
      var.rollout_max_healthy_percentage == 150 &&
      (
        tolist(var.rollout_checkpoint_percentages) == tolist([50]) ||
        tolist(var.rollout_checkpoint_percentages) == tolist([50, 100])
      ) &&
      !var.rollout_scaling_policy_enabled &&
      var.rollout_checkpoint_delay_seconds > 0
    ) : false
  )

  rollout_digest_contract_valid = (
    var.rollout_mode == "NORMAL" ? (
      var.rollout_normal_backend_image_uri != null &&
      var.backend_image_uri == var.rollout_normal_backend_image_uri
      ) : var.rollout_mode == "EXPERIMENT" ? (
      var.rollout_normal_backend_image_uri != null &&
      var.backend_image_uri == var.rollout_normal_backend_image_uri
      ) : var.rollout_mode == "FAULT" ? (
      var.rollout_normal_backend_image_uri != null &&
      var.rollout_fault_backend_image_uri != null &&
      var.rollout_normal_backend_image_uri != var.rollout_fault_backend_image_uri &&
      var.backend_image_uri == var.rollout_fault_backend_image_uri
      ) : var.rollout_mode == "MANUAL_BASELINE" ? (
      var.rollout_normal_backend_image_uri != null &&
      var.rollout_restore_backend_image_uri != null &&
      var.rollout_restore_backend_image_uri == var.rollout_normal_backend_image_uri &&
      var.backend_image_uri == var.rollout_restore_backend_image_uri
    ) : false
  )

  rollout_contract_valid = (
    local.rollout_profile_shape_valid &&
    local.rollout_digest_contract_valid &&
    var.asg_min_size == 2 &&
    var.asg_desired_capacity == 2 &&
    var.asg_max_size == 4
  )
}

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "instance_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "backend" {
  name               = "${local.name}-backend-runtime"
  assume_role_policy = data.aws_iam_policy_document.instance_assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "backend_runtime" {
  statement {
    sid       = "EcrAuthorization"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "BackendImagePull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [var.ecr_repository_arn]
  }

  statement {
    sid     = "RuntimeSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      var.backend_application_secret_arn,
      var.database_master_secret_arn,
      var.redis_auth_secret_arn,
    ]
  }

  statement {
    sid     = "MonitoringEndpointParameter"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.monitoring_endpoint_parameter_name}"
    ]
  }
}

resource "aws_iam_role_policy" "backend_runtime" {
  name   = "${local.name}-backend-runtime"
  role   = aws_iam_role.backend.id
  policy = data.aws_iam_policy_document.backend_runtime.json
}

resource "aws_iam_role_policy_attachment" "profile_image" {
  role       = aws_iam_role.backend.name
  policy_arn = var.profile_image_runtime_policy_arn
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.backend.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "backend" {
  name = "${local.name}-backend-runtime"
  role = aws_iam_role.backend.name
  tags = var.tags
}

resource "aws_lb" "this" {
  name                       = "${local.name}-api"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [var.alb_security_group_id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true
  enable_deletion_protection = false
  idle_timeout               = 60
  tags                       = var.tags
}

resource "aws_lb_target_group" "backend" {
  name                 = "${local.name}-backend"
  port                 = 8080
  protocol             = "HTTP"
  target_type          = "instance"
  vpc_id               = var.vpc_id
  deregistration_delay = 60

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 15
    matcher             = "200"
    path                = "/actuator/health/readiness"
    port                = "9091"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 3
  }

  tags = var.tags
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}

resource "aws_launch_template" "backend" {
  name_prefix            = "${local.name}-backend-"
  image_id               = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  update_default_version = true

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      delete_on_termination = true
      encrypted             = true
      volume_size           = var.root_volume_size_gib
      volume_type           = "gp3"
    }
  }

  iam_instance_profile {
    arn = aws_iam_instance_profile.backend.arn
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 1
    http_tokens                 = "required"
    instance_metadata_tags      = "enabled"
  }

  network_interfaces {
    associate_public_ip_address = false
    delete_on_termination       = true
    device_index                = 0
    security_groups             = [var.backend_security_group_id]
  }

  user_data = base64encode(templatefile("${path.module}/templates/backend-user-data.sh.tftpl", {
    application_secret_arn             = var.backend_application_secret_arn
    alloy_image_reference              = var.alloy_image_reference
    aws_region                         = var.aws_region
    backend_image_uri                  = var.backend_image_uri
    database_address                   = var.database_address
    database_master_secret_arn         = var.database_master_secret_arn
    database_name                      = var.database_name
    database_port                      = var.database_port
    ecr_registry_url                   = split("/", var.ecr_repository_url)[0]
    frontend_origin                    = var.frontend_origin
    google_oauth_redirect_uri          = var.google_oauth_redirect_uri
    monitoring_endpoint_parameter_name = var.monitoring_endpoint_parameter_name
    naver_oauth_redirect_uri           = var.naver_oauth_redirect_uri
    profile_image_bucket_name          = var.profile_image_bucket_name
    profile_image_public_base_url      = var.profile_image_public_base_url
    redis_auth_secret_arn              = var.redis_auth_secret_arn
    redis_port                         = var.redis_port
    redis_primary_endpoint             = var.redis_primary_endpoint
  }))

  tag_specifications {
    resource_type = "instance"
    tags = merge(var.tags, {
      Name            = "${local.name}-backend"
      Service         = "travel-planner-backend"
      Version         = var.alloy_image_reference
      RolloutRevision = var.rollout_revision
    })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = merge(var.tags, { Name = "${local.name}-backend-root" })
  }

  tags = var.tags
}

resource "aws_autoscaling_group" "backend" {
  name             = "${local.name}-backend"
  min_size         = var.asg_min_size
  desired_capacity = var.asg_desired_capacity
  max_size         = var.asg_max_size
  enabled_metrics = [
    "GroupDesiredCapacity",
    "GroupInServiceInstances",
    "GroupPendingInstances",
  ]
  metrics_granularity       = "1Minute"
  health_check_type         = "ELB"
  health_check_grace_period = 300
  default_instance_warmup   = var.instance_warmup_seconds
  vpc_zone_identifier       = var.app_subnet_ids
  target_group_arns         = [aws_lb_target_group.backend.arn]

  launch_template {
    id = aws_launch_template.backend.id
    # A concrete version makes digest/user-data changes visible on the ASG
    # and lets the instance_refresh block roll the existing instances.
    version = aws_launch_template.backend.latest_version
  }

  instance_refresh {
    strategy = "Rolling"

    preferences {
      auto_rollback          = false
      instance_warmup        = var.instance_warmup_seconds
      max_healthy_percentage = var.rollout_max_healthy_percentage
      min_healthy_percentage = var.rollout_min_healthy_percentage
      checkpoint_delay       = var.rollout_checkpoint_delay_seconds
      checkpoint_percentages = var.rollout_checkpoint_percentages
      skip_matching          = true
    }
  }

  dynamic "tag" {
    for_each = merge(var.tags, {
      Name    = "${local.name}-backend"
      Service = "travel-planner-backend"
      Version = var.alloy_image_reference
    })

    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  lifecycle {
    precondition {
      condition = (
        var.asg_min_size == 2 &&
        var.asg_desired_capacity == 2 &&
        var.asg_max_size == 4
      )
      error_message = "The EC2 comparison baseline requires min_size=2, desired_capacity=2, and max_size=4."
    }

    precondition {
      condition     = local.rollout_contract_valid
      error_message = "rollout_mode, Instance Refresh percentages/checkpoints, scaling policy, and normal/fault digests do not match an approved rollout contract."
    }
  }
}

resource "aws_autoscaling_policy" "cpu" {
  count                  = var.rollout_scaling_policy_enabled ? 1 : 0
  name                   = "${local.name}-backend-cpu"
  autoscaling_group_name = aws_autoscaling_group.backend.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    target_value = var.target_cpu_utilization

    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
  }
}
