mock_provider "aws" {}

variables {
  environment  = "dev"
  project_name = "kdt-travelplanner"
  vpc_cidr     = "10.20.0.0/16"
  vpc_id       = "vpc-12345678"
}

run "runtime_ports_are_scoped" {
  command = plan

  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.backend_api.from_port == 8080 &&
      aws_vpc_security_group_ingress_rule.backend_health.from_port == 9091
    )
    error_message = "Only the API and readiness ports may enter backend instances from the ALB."
  }

  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.database_backend.from_port == 5432 &&
      aws_vpc_security_group_ingress_rule.cache_backend.from_port == 6379
    )
    error_message = "Data security groups must expose only PostgreSQL and Redis ports."
  }

  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.backend_api.cidr_ipv4 == null &&
      aws_vpc_security_group_ingress_rule.backend_health.cidr_ipv4 == null
    )
    error_message = "Backend ingress must reference the ALB security group rather than a CIDR."
  }

  assert {
    condition = (
      aws_vpc_security_group_egress_rule.backend_dns_udp.cidr_ipv4 == "10.20.0.2/32" &&
      aws_vpc_security_group_egress_rule.backend_dns_tcp.cidr_ipv4 == "10.20.0.2/32"
    )
    error_message = "DNS egress must be restricted to the VPC Route 53 Resolver."
  }
}
