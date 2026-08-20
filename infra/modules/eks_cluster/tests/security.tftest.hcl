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

variables {
  environment  = "dev"
  project_name = "kdt-travelplanner"
  subnet_ids   = ["subnet-app-a", "subnet-app-c"]
}

run "control_plane_is_private_first_logged_and_encrypted" {
  command = plan

  assert {
    condition = (
      aws_eks_cluster.this.vpc_config[0].endpoint_private_access &&
      aws_eks_cluster.this.vpc_config[0].endpoint_public_access &&
      toset(aws_eks_cluster.this.vpc_config[0].subnet_ids) == toset(var.subnet_ids)
    )
    error_message = "The control plane must always be reachable privately, and must use the exact supplied app subnets."
  }

  assert {
    condition = (
      toset(aws_eks_cluster.this.enabled_cluster_log_types) == toset([
        "api",
        "audit",
        "authenticator",
        "controllerManager",
        "scheduler",
      ])
    )
    error_message = "All five control-plane log types must be enabled."
  }

  assert {
    condition = (
      tolist(aws_eks_cluster.this.encryption_config[0].resources) == tolist(["secrets"]) &&
      aws_eks_cluster.this.encryption_config[0].provider[0].key_arn == aws_kms_key.eks_secrets.arn &&
      aws_kms_key.eks_secrets.enable_key_rotation
    )
    error_message = "Kubernetes Secrets must be encrypted with the dedicated, rotating EKS KMS key."
  }
}

run "nodes_are_private_with_standard_managed_policies" {
  command = plan

  assert {
    condition = (
      toset(aws_eks_node_group.this.subnet_ids) == toset(var.subnet_ids) &&
      aws_eks_node_group.this.scaling_config[0].min_size == 1 &&
      aws_eks_node_group.this.scaling_config[0].max_size == 1 &&
      aws_eks_node_group.this.scaling_config[0].desired_size == 1
    )
    error_message = "Nodes must run only in the private app subnets at the agreed minimum 1/1/1 size."
  }

  assert {
    condition = (
      aws_iam_role_policy_attachment.node_worker_policy.policy_arn == "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy" &&
      aws_iam_role_policy_attachment.node_cni_policy.policy_arn == "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy" &&
      aws_iam_role_policy_attachment.node_ecr_read_only.policy_arn == "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    )
    error_message = "Node role must use the standard AWS worker/CNI/registry-read-only managed policies, not a repository-scoped policy."
  }
}

run "cluster_oidc_provider_trusts_only_sts" {
  command = plan

  assert {
    condition = (
      toset(aws_iam_openid_connect_provider.cluster.client_id_list) == toset(["sts.amazonaws.com"]) &&
      aws_iam_openid_connect_provider.cluster.url == aws_eks_cluster.this.identity[0].oidc[0].issuer
    )
    error_message = "The cluster IRSA OIDC provider must trust only the STS audience and match the cluster's own issuer."
  }
}

run "invalid_scaling_shape_is_rejected" {
  command = plan

  variables {
    node_min_size     = 3
    node_desired_size = 1
    node_max_size     = 1
  }

  expect_failures = [aws_eks_node_group.this]
}

run "too_few_subnets_is_rejected" {
  command = plan

  variables {
    subnet_ids = ["subnet-app-a"]
  }

  expect_failures = [var.subnet_ids]
}
