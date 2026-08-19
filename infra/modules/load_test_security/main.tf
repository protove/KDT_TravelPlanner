locals {
  name = "${var.project_name}-${var.environment}"
}

# The Load Runner belongs to the separately applied dev-load-test State. It
# has no inbound rules and reaches the public ALB and AWS APIs over HTTPS.
resource "aws_security_group" "load_runner" {
  name_prefix            = "${local.name}-load-runner-"
  description            = "SSM-only k6 load runner; no inbound, outbound restricted to ALB/RDS/Redis/AWS APIs"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = merge(var.tags, { Name = "${local.name}-load-runner-sg" })
}

resource "aws_vpc_security_group_egress_rule" "load_runner_https" {
  security_group_id = aws_security_group.load_runner.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
  description       = "k6 HTTPS traffic to the public ALB, plus SSM/S3/ECR/DockerHub"
}

resource "aws_vpc_security_group_egress_rule" "load_runner_dns_udp" {
  security_group_id = aws_security_group.load_runner.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "udp"
  to_port           = 53
  description       = "DNS resolution"
}

resource "aws_vpc_security_group_egress_rule" "load_runner_dns_tcp" {
  security_group_id = aws_security_group.load_runner.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "tcp"
  to_port           = 53
  description       = "DNS fallback"
}

resource "aws_vpc_security_group_egress_rule" "load_runner_database" {
  security_group_id            = aws_security_group.load_runner.id
  referenced_security_group_id = var.database_security_group_id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "Seed and cleanup synthetic load-test data directly in PostgreSQL"
}

resource "aws_vpc_security_group_ingress_rule" "database_load_runner" {
  security_group_id            = var.database_security_group_id
  referenced_security_group_id = aws_security_group.load_runner.id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "PostgreSQL from the Load Runner for seed and cleanup only"
}

resource "aws_vpc_security_group_egress_rule" "load_runner_cache" {
  security_group_id            = aws_security_group.load_runner.id
  referenced_security_group_id = var.cache_security_group_id
  from_port                    = 6379
  ip_protocol                  = "tcp"
  to_port                      = 6379
  description                  = "Seed and cleanup synthetic refresh-token data directly in Redis"
}

resource "aws_vpc_security_group_ingress_rule" "cache_load_runner" {
  security_group_id            = var.cache_security_group_id
  referenced_security_group_id = aws_security_group.load_runner.id
  from_port                    = 6379
  ip_protocol                  = "tcp"
  to_port                      = 6379
  description                  = "Redis from the Load Runner for seed and cleanup only"
}
