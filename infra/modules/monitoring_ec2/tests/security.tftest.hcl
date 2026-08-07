mock_provider "aws" {
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
      private_ip = "10.0.1.53"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::test-monitoring-config"
      id  = "test-monitoring-config"
    }
  }
}

variables {
  app_subnet_id                      = "subnet-app-a"
  aws_region                         = "ap-northeast-2"
  environment                        = "dev"
  monitoring_bucket_name             = "kdt-travelplanner-dev-monitoring-config-123456789012"
  monitoring_endpoint_parameter_name = "/kdt-travelplanner/dev/monitoring-endpoint"
  monitoring_security_group_id       = "sg-monitoring"
  project_name                       = "kdt-travelplanner"
}

run "monitoring_ec2_is_private_and_encrypted" {
  command = plan

  assert {
    condition = (
      !aws_instance.monitoring.associate_public_ip_address &&
      aws_instance.monitoring.metadata_options[0].http_tokens == "required" &&
      aws_instance.monitoring.root_block_device[0].encrypted &&
      aws_instance.monitoring.root_block_device[0].volume_type == "gp3"
    )
    error_message = "Monitoring EC2 must have no public IP, require IMDSv2 and use encrypted gp3 storage."
  }

  assert {
    condition     = aws_ssm_parameter.monitoring_endpoint.name == var.monitoring_endpoint_parameter_name
    error_message = "Monitoring endpoint must be published under the agreed SSM parameter path."
  }
}

run "monitoring_config_bucket_blocks_public_access" {
  command = plan

  assert {
    condition = (
      aws_s3_bucket_public_access_block.monitoring_config.block_public_acls &&
      aws_s3_bucket_public_access_block.monitoring_config.block_public_policy &&
      aws_s3_bucket_public_access_block.monitoring_config.ignore_public_acls &&
      aws_s3_bucket_public_access_block.monitoring_config.restrict_public_buckets
    )
    error_message = "Monitoring config bucket must block all public access."
  }
}


