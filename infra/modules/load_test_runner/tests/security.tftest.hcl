mock_provider "aws" {
  override_during = plan

  mock_data "aws_ssm_parameter" {
    defaults = {
      value = "ami-0123456789abcdef0"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"ec2.amazonaws.com\"}}]}"
    }
  }

  mock_resource "aws_instance" {
    defaults = {
      id         = "i-0123456789abcdef0"
      private_ip = "10.0.1.77"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::test-load-test-evidence"
      id  = "test-load-test-evidence"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn  = "arn:aws:iam::123456789012:role/test-load-runner-runtime"
      name = "test-load-runner-runtime"
    }
  }
}

variables {
  app_subnet_id            = "subnet-app-a"
  aws_region               = "ap-northeast-2"
  environment              = "dev"
  evidence_bucket_name     = "kdt-travelplanner-dev-load-test-evidence-123456789012"
  k6_image_reference       = "grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755"
  project_name             = "kdt-travelplanner"
  runner_security_group_id = "sg-load-runner"
  source_commit_sha        = "0123456789abcdef0123456789abcdef01234567"
}

run "load_runner_is_private_and_encrypted" {
  command = plan

  assert {
    condition = (
      !aws_instance.load_runner.associate_public_ip_address &&
      aws_instance.load_runner.metadata_options[0].http_tokens == "required" &&
      aws_instance.load_runner.metadata_options[0].http_put_response_hop_limit == 1 &&
      aws_instance.load_runner.root_block_device[0].encrypted &&
      aws_instance.load_runner.root_block_device[0].volume_type == "gp3" &&
      aws_instance.load_runner.user_data_replace_on_change &&
      startswith(aws_instance.load_runner.user_data, "#!/usr/bin/env bash") &&
      strcontains(aws_instance.load_runner.user_data, var.source_commit_sha) &&
      strcontains(aws_instance.load_runner.user_data, "base-ready.json") &&
      strcontains(aws_instance.load_runner.user_data, "command -v aws") &&
      strcontains(aws_instance.load_runner.user_data, "command -v curl") &&
      strcontains(aws_instance.load_runner.user_data, "chmod 0600") &&
      !strcontains(aws_instance.load_runner.user_data, "dnf install -y docker git python3-pip curl") &&
      !strcontains(aws_instance.load_runner.user_data, "git clone") &&
      !strcontains(aws_instance.load_runner.user_data, "git fetch") &&
      !strcontains(aws_instance.load_runner.user_data, "docker pull") &&
      !strcontains(aws_instance.load_runner.user_data, "source_repository_url") &&
      !strcontains(aws_instance.load_runner.user_data, ":latest")
    )
    error_message = "Load Runner must have no public IP, require IMDSv2, use encrypted gp3 storage, emit only a base receipt, and defer source/image/mock delivery to the private S3 plus SSM bootstrap."
  }
}

run "evidence_bucket_blocks_public_access_and_is_encrypted" {
  command = plan

  assert {
    condition = (
      aws_s3_bucket_public_access_block.evidence.block_public_acls &&
      aws_s3_bucket_public_access_block.evidence.block_public_policy &&
      aws_s3_bucket_public_access_block.evidence.ignore_public_acls &&
      aws_s3_bucket_public_access_block.evidence.restrict_public_buckets
    )
    error_message = "Evidence bucket must block all public access."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.evidence.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "Evidence bucket must use SSE-S3 AES256 encryption."
  }

  assert {
    condition = (
      aws_s3_bucket_lifecycle_configuration.evidence.rule[0].status == "Enabled" &&
      aws_s3_bucket_lifecycle_configuration.evidence.rule[0].expiration[0].days == var.evidence_retention_days
    )
    error_message = "Evidence bucket must expire objects after evidence_retention_days."
  }
}

# NOTE: this file does not assert on data.aws_iam_policy_document.*.json
# content. Under mock_provider, resolving that computed value requires
# command = apply, which then requires every other computed attribute on
# every mocked resource (aws_iam_role, aws_s3_bucket, ...) to also have an
# explicit mock default or Terraform reports "Provider produced inconsistent
# final plan" (mismatched random placeholder values between the plan and
# apply passes). monitoring_ec2's test suite avoids this same trap by never
# asserting on a data source's .json output either. The IAM statements in
# main.tf (evidence bucket read/write/list, conditional Secrets Manager read
# when secrets_arns is non-empty) are verified by code review instead.

run "evidence_operator_read_policy_is_unattached" {
  command = plan

  assert {
    condition     = aws_iam_policy.evidence_operator_read.name == "kdt-travelplanner-dev-load-test-evidence-operator-read"
    error_message = "Operator read policy must be created with a predictable name so it can be located and manually attached."
  }
}

run "unpinned_k6_image_is_rejected" {
  command = plan

  variables {
    k6_image_reference = "grafana/k6:latest"
  }

  expect_failures = [var.k6_image_reference]
}

run "k6_image_without_digest_is_rejected" {
  command = plan

  variables {
    k6_image_reference = "grafana/k6:0.54.0"
  }

  expect_failures = [var.k6_image_reference]
}

run "source_commit_sha_must_be_exact" {
  command = plan

  variables {
    source_commit_sha = "not-a-commit"
  }

  expect_failures = [var.source_commit_sha]
}

run "runner_instance_type_allows_only_registered_shapes" {
  command = plan

  variables {
    instance_type = "m6i.large"
  }

  expect_failures = [var.instance_type]
}

run "runner_instance_type_accepts_scrum80_shapes" {
  command = plan

  variables {
    instance_type = "c6i.2xlarge"
  }

  assert {
    condition     = var.instance_type == "c6i.2xlarge"
    error_message = "SCRUM-80 primary Runner shape must be accepted."
  }
}

run "runner_instance_type_rejects_unregistered_c6i_shape" {
  command = plan

  variables {
    instance_type = "c6i.8xlarge"
  }

  expect_failures = [var.instance_type]
}

run "eks_observation_scope_accepts_only_the_disposable_stack" {
  command = plan

  variables {
    eks_observation_stack = "dev-eks"
  }

  assert {
    condition     = var.eks_observation_stack == "dev-eks"
    error_message = "EKS observation permissions must be bound to the disposable dev-eks stack."
  }
}

run "eks_observation_scope_rejects_other_stacks" {
  command = plan

  variables {
    eks_observation_stack = "dev-runtime"
  }

  expect_failures = [var.eks_observation_stack]
}
