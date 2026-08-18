mock_provider "aws" {
  override_during = plan

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn    = "arn:aws:s3:::kdt-travelplanner-tfstate-123456789012-ap-northeast-2"
      bucket = "kdt-travelplanner-tfstate-123456789012-ap-northeast-2"
      id     = "kdt-travelplanner-tfstate-123456789012-ap-northeast-2"
    }
  }
}

variables {
  bucket_name = "kdt-travelplanner-tfstate-123456789012-ap-northeast-2"
  state_keys = [
    "dev/terraform.tfstate",
    "dev-load-test/terraform.tfstate",
    "dev-runtime/terraform.tfstate",
  ]
}

run "state_bucket_security_controls" {
  command = plan

  assert {
    condition     = aws_s3_bucket.this.force_destroy == false
    error_message = "The state bucket must never force-delete objects."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.this.block_public_acls &&
      aws_s3_bucket_public_access_block.this.block_public_policy &&
      aws_s3_bucket_public_access_block.this.ignore_public_acls &&
      aws_s3_bucket_public_access_block.this.restrict_public_buckets
    )
    error_message = "All S3 public access controls must be enabled."
  }

  assert {
    condition     = aws_s3_bucket_ownership_controls.this.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "The state bucket must disable ACL ownership with BucketOwnerEnforced."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "The state bucket must explicitly use SSE-S3 AES256 encryption."
  }

  assert {
    condition     = aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Enabled"
    error_message = "The state bucket must have versioning enabled."
  }
}

run "state_access_policy_is_least_privilege" {
  command = plan

  assert {
    condition     = toset(data.aws_iam_policy_document.state_access.statement[1].actions) == toset(["s3:GetObject", "s3:PutObject"])
    error_message = "State objects must be readable and writable but not deletable."
  }

  assert {
    condition     = toset(data.aws_iam_policy_document.state_access.statement[2].actions) == toset(["s3:DeleteObject", "s3:GetObject", "s3:PutObject"])
    error_message = "Only lock objects may be deleted by day-to-day Terraform operators."
  }

  assert {
    condition     = alltrue([for resource in data.aws_iam_policy_document.state_access.statement[2].resources : endswith(resource, ".tflock")])
    error_message = "DeleteObject permissions must be scoped to .tflock objects."
  }

  assert {
    condition = toset(data.aws_iam_policy_document.state_access.statement[1].resources) == toset([
      "arn:aws:s3:::kdt-travelplanner-tfstate-123456789012-ap-northeast-2/dev/terraform.tfstate",
      "arn:aws:s3:::kdt-travelplanner-tfstate-123456789012-ap-northeast-2/dev-load-test/terraform.tfstate",
      "arn:aws:s3:::kdt-travelplanner-tfstate-123456789012-ap-northeast-2/dev-runtime/terraform.tfstate",
    ])
    error_message = "Day-to-day State access must include only dev, dev-runtime and dev-load-test State objects."
  }
}
