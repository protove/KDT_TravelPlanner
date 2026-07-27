terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ap-northeast-2" # 서울 리전
}

# S3 버킷 생성
resource "aws_s3_bucket" "profile_images" {
  bucket = var.bucket_name
}

# 버킷 비공개로 잠금 — CloudFront를 통해서만 접근 가능
resource "aws_s3_bucket_public_access_block" "profile_images_access" {
  bucket = aws_s3_bucket.profile_images.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CORS 설정 (프론트가 브라우저에서 S3로 업로드할 때 필요, 다운로드는 CDN이 담당)
resource "aws_s3_bucket_cors_configuration" "profile_images_cors" {
  bucket = aws_s3_bucket.profile_images.id

  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = var.allowed_origins
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

# CloudFront가 이 S3 버킷에 접근할 수 있는 통로
resource "aws_cloudfront_origin_access_control" "profile_images_oac" {
  name                              = "${var.bucket_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront 배포
resource "aws_cloudfront_distribution" "profile_images_cdn" {
  enabled = true

  origin {
    domain_name              = aws_s3_bucket.profile_images.bucket_regional_domain_name
    origin_id                = "profileImagesS3Origin"
    origin_access_control_id = aws_cloudfront_origin_access_control.profile_images_oac.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "profileImagesS3Origin"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# S3 버킷 정책
resource "aws_s3_bucket_policy" "profile_images_cloudfront_only" {
  bucket = aws_s3_bucket.profile_images.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontServicePrincipal"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.profile_images.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.profile_images_cdn.arn
          }
        }
      }
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.profile_images_access]
}

# 백엔드가 업로드용으로 쓸 IAM 사용자
resource "aws_iam_user" "backend_uploader" {
  name = "${var.bucket_name}-backend-uploader"
}

resource "aws_iam_user_policy" "backend_uploader_policy" {
  name = "s3-put-object-policy"
  user = aws_iam_user.backend_uploader.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.profile_images.arn}/*"
      }
    ]
  })
}

resource "aws_iam_access_key" "backend_uploader_key" {
  user = aws_iam_user.backend_uploader.name
}
