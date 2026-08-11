locals {
  name = "${var.project_name}-${var.environment}"
}

# ── Evidence 저장용 S3 버킷 ─────────────────────────────────────
# monitoring_config 버킷과 같은 이유로 force_destroy=true: dev-runtime의
# plan→apply→test→destroy 생명주기 안에 있는 자산이다. 장기 보존이 필요한
# evidence는 Plan 05에서 로컬로 내려받은 뒤 별도 관리한다.
resource "aws_s3_bucket" "evidence" {
  bucket        = var.evidence_bucket_name
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# D-004(보존기간·KMS) 2026-08-11 승인: AES256(SSE-S3), 30일 보존 (KMS 미사용).
# 근거는 aws-load-test-handoff/decisions/DECISION_LOG.md 참고.
resource "aws_s3_bucket_lifecycle_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    id     = "expire-load-test-evidence"
    status = "Enabled"

    filter {}

    expiration {
      days = var.evidence_retention_days
    }
  }
}

# ── Load Runner IAM 권한 ────────────────────────────────────────
data "aws_iam_policy_document" "instance_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "load_runner" {
  name               = "${local.name}-load-runner-runtime"
  assume_role_policy = data.aws_iam_policy_document.instance_assume_role.json
  tags               = var.tags
}

# aws-load-test-handoff/contracts/EVIDENCE_BUNDLE_CONTRACT.md fixes this top
# level prefix (only the <run-id> segment is dynamic, decided at Plan 03
# runtime). Scoping the Runner's own IAM to this prefix, rather than the
# whole bucket, mirrors the ListBucket-by-prefix pattern already used by
# infra/modules/profile_image (ProfileImageLookup statement).
locals {
  evidence_prefix = "evidence/aws-load-tests"
}

data "aws_iam_policy_document" "load_runner_runtime" {
  statement {
    sid       = "LoadTestEvidenceObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/${local.evidence_prefix}/*"]
  }

  statement {
    sid       = "LoadTestEvidenceListing"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.evidence.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.evidence_prefix}/*"]
    }
  }

  # seed/cleanup adapter가 DB 자격증명(전용 test Secret)을 읽을 수 있도록
  # 준비해두는 자리. secrets_arns가 비어 있으면 이 statement는 생성되지 않는다.
  dynamic "statement" {
    for_each = length(var.secrets_arns) > 0 ? [1] : []
    content {
      sid       = "LoadTestSeedCredentialsRead"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = var.secrets_arns
    }
  }

  # Redis는 Secret이 아니라 ElastiCache RBAC + IAM 인증을 쓴다 (D-001-R1 후속
  # Seed/Cleanup 최소권한). elasticache:Connect는 User ARN과 Replication
  # Group ARN 둘 다에 대한 권한을 요구한다.
  dynamic "statement" {
    for_each = length(var.redis_iam_auth_arns) > 0 ? [1] : []
    content {
      sid       = "LoadTestRedisIamAuth"
      actions   = ["elasticache:Connect"]
      resources = var.redis_iam_auth_arns
    }
  }
}

resource "aws_iam_role_policy" "load_runner_runtime" {
  name   = "${local.name}-load-runner-runtime"
  role   = aws_iam_role.load_runner.id
  policy = data.aws_iam_policy_document.load_runner_runtime.json
}

# ── 운영자용 Evidence 읽기 권한 (unattached) ────────────────────
# Plan02 보안경계(02_AWS_LOAD_RUNNER_INFRA_PLAN.md 52줄) "operator read" 요구사항.
# profile_image 모듈의 runtime_policy_arn과 동일한 패턴: 여기서는 고객 관리형
# 정책만 만들고 attach하지 않는다. 실제 연결은 사람이 SSO Permission Set이나
# 운영 Role에 수동으로 붙인다 (infra/README.md 참고).
data "aws_iam_policy_document" "evidence_operator_read" {
  statement {
    sid       = "LoadTestEvidenceOperatorRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/${local.evidence_prefix}/*"]
  }

  statement {
    sid       = "LoadTestEvidenceOperatorListing"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.evidence.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.evidence_prefix}/*"]
    }
  }
}

resource "aws_iam_policy" "evidence_operator_read" {
  name        = "${local.name}-load-test-evidence-operator-read"
  description = "Unattached least-privilege read-only access to the load-test evidence prefix, for manual attachment to an operator SSO Permission Set or Role."
  policy      = data.aws_iam_policy_document.evidence_operator_read.json
  tags        = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.load_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "load_runner" {
  name = "${local.name}-load-runner-runtime"
  role = aws_iam_role.load_runner.name
  tags = var.tags
}

# ── Load Runner EC2 (ASG 아님, 단일 고정 인스턴스) ────────────────
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "load_runner" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  subnet_id              = var.app_subnet_id
  iam_instance_profile   = aws_iam_instance_profile.load_runner.name
  vpc_security_group_ids = [var.runner_security_group_id]

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

  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/templates/runner-user-data.sh.tftpl", {
    aws_region            = var.aws_region
    botocore_version      = var.botocore_version
    k6_image_reference    = var.k6_image_reference
    source_commit_sha     = var.source_commit_sha
    source_repository_url = var.source_repository_url
  })

  tags = merge(var.tags, {
    Name    = "${local.name}-load-runner"
    Service = "travel-planner-load-runner"
  })
}
