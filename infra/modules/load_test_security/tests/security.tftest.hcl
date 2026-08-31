mock_provider "aws" {
  override_during = plan

  mock_resource "aws_security_group" {
    defaults = {
      id = "sg-load-runner"
    }
  }
}

variables {
  cache_security_group_id    = "sg-cache"
  database_security_group_id = "sg-database"
  environment                = "dev"
  project_name               = "kdt-travelplanner"
  vpc_cidr                   = "10.20.0.0/16"
  vpc_id                     = "vpc-12345678"
}

run "load_runner_has_no_ingress" {
  command = plan

  assert {
    condition     = aws_security_group.load_runner.revoke_rules_on_delete
    error_message = "Load Runner security group must revoke rules on delete and define no broad ingress."
  }

  assert {
    condition = (
      aws_vpc_security_group_egress_rule.load_runner_https.cidr_ipv4 == "0.0.0.0/0" &&
      aws_vpc_security_group_egress_rule.load_runner_https.from_port == 443 &&
      aws_vpc_security_group_egress_rule.load_runner_https.to_port == 443
    )
    error_message = "Load Runner must reach the public ALB and AWS APIs only through the reviewed HTTPS egress."
  }

  assert {
    condition = (
      aws_vpc_security_group_egress_rule.load_runner_dns_udp.cidr_ipv4 == "10.20.0.2/32" &&
      aws_vpc_security_group_egress_rule.load_runner_dns_tcp.cidr_ipv4 == "10.20.0.2/32"
    )
    error_message = "Load Runner DNS egress must be restricted to the VPC Route 53 Resolver."
  }
}

run "data_access_uses_security_group_references" {
  command = plan

  assert {
    condition = (
      aws_vpc_security_group_egress_rule.load_runner_database.referenced_security_group_id == var.database_security_group_id &&
      aws_vpc_security_group_egress_rule.load_runner_database.cidr_ipv4 == null &&
      aws_vpc_security_group_ingress_rule.database_load_runner.referenced_security_group_id == aws_security_group.load_runner.id &&
      aws_vpc_security_group_egress_rule.load_runner_cache.referenced_security_group_id == var.cache_security_group_id &&
      aws_vpc_security_group_egress_rule.load_runner_cache.cidr_ipv4 == null &&
      aws_vpc_security_group_ingress_rule.cache_load_runner.referenced_security_group_id == aws_security_group.load_runner.id
    )
    error_message = "Load Runner must reach PostgreSQL and Redis through security-group references, not CIDR blocks."
  }
}

run "eks_mock_ingress_is_exact_cluster_sg_only" {
  command = plan

  variables {
    eks_cluster_security_group_id = "sg-eks-cluster"
  }

  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.load_runner_google_mock.referenced_security_group_id == "sg-eks-cluster" &&
      aws_vpc_security_group_ingress_rule.load_runner_google_mock.from_port == 8080 &&
      aws_vpc_security_group_ingress_rule.load_runner_google_mock.to_port == 8080 &&
      aws_vpc_security_group_ingress_rule.load_runner_google_mock.cidr_ipv4 == null
    )
    error_message = "EKS mock ingress must allow TCP/8080 only from the exact cluster security group."
  }
}
