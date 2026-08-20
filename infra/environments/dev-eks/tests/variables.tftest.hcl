mock_provider "aws" {
  override_during = plan

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"eks.amazonaws.com\"}}]}"
    }
  }

  mock_resource "aws_kms_key" {
    defaults = {
      arn    = "arn:aws:kms:ap-northeast-2:123456789012:key/12345678-1234-1234-1234-123456789012"
      key_id = "12345678-1234-1234-1234-123456789012"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn  = "arn:aws:iam::123456789012:role/kdt-travelplanner-dev-eks-cluster"
      name = "kdt-travelplanner-dev-eks-cluster"
    }
  }

  mock_resource "aws_eks_cluster" {
    defaults = {
      arn      = "arn:aws:eks:ap-northeast-2:123456789012:cluster/kdt-travelplanner-dev-eks"
      endpoint = "https://EXAMPLE.gr7.ap-northeast-2.eks.amazonaws.com"
      identity = [{
        oidc = [{
          issuer = "https://oidc.eks.ap-northeast-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE"
        }]
      }]
      certificate_authority = [{
        data = "LS0tLS1CRUdJTi0tLS0t"
      }]
    }
  }

  mock_resource "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.ap-northeast-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE"
    }
  }

  mock_resource "aws_eks_node_group" {
    defaults = {
      arn    = "arn:aws:eks:ap-northeast-2:123456789012:nodegroup/kdt-travelplanner-dev-eks/kdt-travelplanner-dev-eks-nodes/abcd1234"
      status = "ACTIVE"
    }
  }
}

mock_provider "tls" {
  mock_data "tls_certificate" {
    defaults = {
      certificates = [{
        sha1_fingerprint = "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"
      }]
    }
  }
}

override_data {
  target = data.terraform_remote_state.persistent
  values = {
    outputs = {
      app_subnet_ids = ["subnet-app-a", "subnet-app-b"]
      vpc_id         = "vpc-12345678"
    }
  }
}

variables {
  aws_account_id = "123456789012"
  aws_region     = "ap-northeast-2"
  state_bucket   = "kdt-travelplanner-tfstate-123456789012-ap-northeast-2"
}

run "defaults_produce_expected_cluster_and_node_names" {
  command = plan

  assert {
    condition = (
      module.eks_cluster.cluster_name == "kdt-travelplanner-dev-eks" &&
      module.eks_cluster.node_group_name == "kdt-travelplanner-dev-eks-nodes" &&
      output.target_persistent_state_key == var.persistent_state_key
    )
    error_message = "dev-eks must name resources from project_name/environment and read only the configured persistent dev State key (never dev-runtime)."
  }
}

run "invalid_account_id_is_rejected" {
  command = plan

  variables {
    aws_account_id = "not-an-account-id"
  }

  expect_failures = [var.aws_account_id]
}

run "invalid_kubernetes_version_is_rejected" {
  command = plan

  variables {
    kubernetes_version = "1.3"
  }

  expect_failures = [var.kubernetes_version]
}
