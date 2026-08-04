mock_provider "aws" {
  mock_resource "aws_db_instance" {
    defaults = {
      address = "database.internal"
      db_name = "travel_diary_dev"
      port    = 5432
      master_user_secret = [{
        kms_key_id    = "kms-key"
        secret_arn    = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:rds"
        secret_status = "active"
      }]
    }
  }

  mock_resource "aws_elasticache_replication_group" {
    defaults = {
      port                     = 6379
      primary_endpoint_address = "redis.internal"
    }
  }
}

mock_provider "random" {
  mock_resource "random_password" {
    defaults = {
      result = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZab"
    }
  }
}

variables {
  cache_security_group_id    = "sg-cache"
  data_subnet_ids            = ["subnet-data-a", "subnet-data-c"]
  database_security_group_id = "sg-database"
  environment                = "dev"
  postgres_engine_version    = "17.8"
  project_name               = "kdt-travelplanner"
}

run "data_services_are_private_and_encrypted" {
  command = plan

  assert {
    condition = (
      !aws_db_instance.this.publicly_accessible &&
      !aws_db_instance.this.multi_az &&
      aws_db_instance.this.storage_encrypted &&
      aws_db_instance.this.manage_master_user_password &&
      !aws_db_instance.this.auto_minor_version_upgrade
    )
    error_message = "RDS must be private, encrypted, Single-AZ, patch-pinned and use an RDS-managed password."
  }

  assert {
    condition = (
      aws_elasticache_replication_group.this.num_cache_clusters == 1 &&
      aws_elasticache_replication_group.this.at_rest_encryption_enabled &&
      aws_elasticache_replication_group.this.transit_encryption_enabled &&
      aws_elasticache_replication_group.this.transit_encryption_mode == "required" &&
      aws_elasticache_replication_group.this.auth_token_update_strategy == "SET"
    )
    error_message = "Redis must be a single encrypted and authenticated node."
  }

  assert {
    condition     = aws_db_instance.this.skip_final_snapshot && !aws_db_instance.this.deletion_protection
    error_message = "The reproducible dev runtime must be destroyable without a final snapshot."
  }
}
