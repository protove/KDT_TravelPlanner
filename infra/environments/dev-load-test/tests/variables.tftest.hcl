mock_provider "aws" {}

override_data {
  target = data.terraform_remote_state.persistent
  values = {
    outputs = {
      app_subnet_ids = ["subnet-app-a", "subnet-app-b"]
      vpc_cidr       = "10.20.0.0/16"
      vpc_id         = "vpc-12345678"
    }
  }
}

override_data {
  target = data.terraform_remote_state.runtime
  values = {
    outputs = {
      cache_security_group_id     = "sg-cache"
      database_security_group_id  = "sg-database"
      cluster_security_group_id   = "sg-eks-cluster"
      private_zone_id             = "ZPRIVATE"
      private_zone_name           = "dev-eks.kdt-travelplanner.internal"
      redis_load_test_user_arn    = "arn:aws:elasticache:ap-northeast-2:123456789012:user:test-user"
      redis_replication_group_arn = "arn:aws:elasticache:ap-northeast-2:123456789012:replicationgroup:test-cache"
    }
  }
}

variables {
  aws_account_id                = "123456789012"
  aws_region                    = "ap-northeast-2"
  load_runner_source_commit_sha = "0123456789abcdef0123456789abcdef01234567"
  state_bucket                  = "kdt-travelplanner-tfstate-123456789012-ap-northeast-2"
}

run "rejects_rds_master_secret" {
  command = plan

  variables {
    test_db_secret_arn = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:rds!db-example"
  }

  expect_failures = [var.test_db_secret_arn]
}

run "rejects_different_account_secret" {
  command = plan

  variables {
    test_db_secret_arn = "arn:aws:secretsmanager:ap-northeast-2:999999999999:secret:kdt-travelplanner-dev/loadtest/db-ABC123"
  }

  expect_failures = [var.test_db_secret_arn]
}

run "accepts_dev_eks_as_the_disposable_runtime_target" {
  command = plan

  variables {
    runtime_state_key  = "dev-eks/terraform.tfstate"
    test_db_secret_arn = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:kdt-travelplanner-dev/loadtest/db-ABC123"
  }

  assert {
    condition     = output.target_runtime_state_key == "dev-eks/terraform.tfstate"
    error_message = "dev-load-test must reuse the same Runner contract when the disposable runtime target is dev-eks."
  }
}
