locals {
  name = "${var.project_name}-${var.environment}"
}

# ── 설정 파일용 S3 버킷 ─────────────────────────────────────────
# 지속 자원(S3 프론트, 프로필 이미지)과 다르게, 이 버킷은 설정 파일만
# 담는 용도라 force_destroy=true로 둠 (dev-runtime 생명주기: plan→apply→test→destroy)
resource "aws_s3_bucket" "monitoring_config" {
  bucket        = var.monitoring_bucket_name
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_public_access_block" "monitoring_config" {
  bucket                  = aws_s3_bucket.monitoring_config.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "monitoring_config" {
  bucket = aws_s3_bucket.monitoring_config.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "monitoring_config" {
  bucket = aws_s3_bucket.monitoring_config.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ── 기존 로컬 monitoring/ 폴더 파일들을 그대로 S3에 업로드 ──────────
# 내용을 다시 타이핑하지 않고, 이미 검증된 로컬 설정을 그대로 재사용함
resource "aws_s3_object" "prometheus_config" {
  bucket = aws_s3_bucket.monitoring_config.id
  key    = "prometheus/prometheus.yml"
  source = "${path.module}/../../../monitoring/prometheus/prometheus.ec2.yml"
  etag   = filemd5("${path.module}/../../../monitoring/prometheus/prometheus.ec2.yml")
}

resource "aws_s3_object" "loki_config" {
  bucket = aws_s3_bucket.monitoring_config.id
  key    = "loki/loki.yml"
  source = "${path.module}/../../../monitoring/loki/loki.prod.yml"
  etag   = filemd5("${path.module}/../../../monitoring/loki/loki.prod.yml")
}

resource "aws_s3_object" "grafana_datasources" {
  bucket = aws_s3_bucket.monitoring_config.id
  key    = "grafana/provisioning/datasources/datasources.yml"
  source = "${path.module}/../../../monitoring/grafana/provisioning/datasources/datasources.ec2.yml"
  etag   = filemd5("${path.module}/../../../monitoring/grafana/provisioning/datasources/datasources.ec2.yml")
}

resource "aws_s3_object" "grafana_dashboards_provisioning" {
  bucket = aws_s3_bucket.monitoring_config.id
  key    = "grafana/provisioning/dashboards/dashboards.yml"
  source = "${path.module}/../../../monitoring/grafana/provisioning/dashboards/dashboards.yml"
  etag   = filemd5("${path.module}/../../../monitoring/grafana/provisioning/dashboards/dashboards.yml")
}

resource "aws_s3_object" "grafana_dashboard_backend_overview" {
  bucket = aws_s3_bucket.monitoring_config.id
  key    = "grafana/dashboards/backend-overview.json"
  source = "${path.module}/../../../monitoring/grafana/dashboards/backend-overview.json"
  etag   = filemd5("${path.module}/../../../monitoring/grafana/dashboards/backend-overview.json")
}

# ── Monitoring EC2 IAM 권한 ─────────────────────────────────────
data "aws_iam_policy_document" "instance_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "monitoring" {
  name               = "${local.name}-monitoring-runtime"
  assume_role_policy = data.aws_iam_policy_document.instance_assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "monitoring_runtime" {
  statement {
    sid     = "MonitoringConfigDownload"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.monitoring_config.arn,
      "${aws_s3_bucket.monitoring_config.arn}/*",
    ]
  }

  # Prometheus EC2 Service Discovery — 조회 전용, 리소스 변경 권한 없음
  statement {
    sid       = "PrometheusEc2Discovery"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }

  # Grafana CloudWatch Data Source — 조회 전용
  statement {
    sid = "GrafanaCloudWatchDataSource"
    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
      "cloudwatch:DescribeAlarmsForMetric",
      "tag:GetResources",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "monitoring_runtime" {
  name   = "${local.name}-monitoring-runtime"
  role   = aws_iam_role.monitoring.id
  policy = data.aws_iam_policy_document.monitoring_runtime.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "monitoring" {
  name = "${local.name}-monitoring-runtime"
  role = aws_iam_role.monitoring.name
  tags = var.tags
}

# ── Monitoring EC2 (ASG 아님, 단일 고정 인스턴스) ─────────────────
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "monitoring" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  subnet_id              = var.app_subnet_id
  iam_instance_profile   = aws_iam_instance_profile.monitoring.name
  vpc_security_group_ids = [var.monitoring_security_group_id]

  associate_public_ip_address = false

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 1
    http_tokens                 = "required"
  }

  root_block_device {
    encrypted   = true
    volume_size = var.root_volume_size_gib
    volume_type = "gp3"
  }

  user_data = base64encode(templatefile("${path.module}/templates/monitoring-user-data.sh.tftpl", {
    aws_region             = var.aws_region
    monitoring_bucket_name = aws_s3_bucket.monitoring_config.id
  }))

  tags = merge(var.tags, {
    Name    = "${local.name}-monitoring"
    Service = "travel-planner-monitoring"
  })
}

# ── Backend EC2들이 이 Monitoring EC2를 찾을 수 있도록 주소를 SSM에 발행 ──
# EC2가 스스로 등록하는 방식이 아니라, Terraform이 aws_instance의
# private_ip를 그대로 SSM에 써두는 결정론적 방식 (더 단순하고 안전함)
resource "aws_ssm_parameter" "monitoring_endpoint" {
  name  = var.monitoring_endpoint_parameter_name
  type  = "String"
  value = aws_instance.monitoring.private_ip
  tags  = var.tags
}
