locals {
  github_oidc_audience = "sts.amazonaws.com"
  github_oidc_issuer   = "https://token.actions.githubusercontent.com"
  github_oidc_subject  = "repo:${var.github_organization}/${var.github_repository}:environment:${var.environment}"
  role_name            = "${var.project_name}-${var.environment}-github-ecr-publisher"

  github_assume_role_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowGitHubDevEnvironment"
        Effect = "Allow"
        Action = ["sts:AssumeRoleWithWebIdentity"]
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = local.github_oidc_audience
            "token.actions.githubusercontent.com:sub" = local.github_oidc_subject
          }
        }
      },
    ]
  }

  ecr_push_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AuthenticateToEcr"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Sid    = "PushAndVerifyBackendImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
        ]
        Resource = [var.ecr_repository_arn]
      },
    ]
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = local.github_oidc_issuer
  client_id_list = [local.github_oidc_audience]
  tags           = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "publisher" {
  name                 = local.role_name
  description          = "GitHub Actions ${var.environment} Environment publisher for the backend ECR repository"
  assume_role_policy   = jsonencode(local.github_assume_role_policy)
  max_session_duration = 3600
  tags                 = var.tags
}

resource "aws_iam_role_policy" "ecr_push" {
  name   = "${local.role_name}-push"
  role   = aws_iam_role.publisher.name
  policy = jsonencode(local.ecr_push_policy)
}
