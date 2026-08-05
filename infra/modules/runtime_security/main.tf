locals {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_security_group" "alb" {
  name_prefix            = "${local.name}-alb-"
  description            = "Public HTTPS entry point for the backend API"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = merge(var.tags, { Name = "${local.name}-alb-sg" })
}

resource "aws_security_group" "backend" {
  name_prefix            = "${local.name}-backend-"
  description            = "Private backend instances behind the ALB"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = merge(var.tags, { Name = "${local.name}-backend-sg" })
}

resource "aws_security_group" "database" {
  name_prefix            = "${local.name}-database-"
  description            = "Private PostgreSQL access from backend instances"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = merge(var.tags, { Name = "${local.name}-database-sg" })
}

resource "aws_security_group" "cache" {
  name_prefix            = "${local.name}-cache-"
  description            = "Private Redis access from backend instances"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = merge(var.tags, { Name = "${local.name}-cache-sg" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  ip_protocol       = "tcp"
  to_port           = 80
  description       = "HTTP redirect entry point"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
  description       = "Public HTTPS API traffic"
}

resource "aws_vpc_security_group_egress_rule" "alb_backend_api" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 8080
  ip_protocol                  = "tcp"
  to_port                      = 8080
  description                  = "Forward API traffic to backend instances"
}

resource "aws_vpc_security_group_egress_rule" "alb_backend_health" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 9091
  ip_protocol                  = "tcp"
  to_port                      = 9091
  description                  = "Read backend readiness health"
}

resource "aws_vpc_security_group_ingress_rule" "backend_api" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8080
  ip_protocol                  = "tcp"
  to_port                      = 8080
  description                  = "API traffic from the ALB only"
}

resource "aws_vpc_security_group_ingress_rule" "backend_health" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 9091
  ip_protocol                  = "tcp"
  to_port                      = 9091
  description                  = "Readiness health checks from the ALB only"
}

resource "aws_vpc_security_group_egress_rule" "backend_https" {
  security_group_id = aws_security_group.backend.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
  description       = "ECR, S3, Secrets Manager and external HTTPS APIs"
}

resource "aws_vpc_security_group_egress_rule" "backend_dns_udp" {
  security_group_id = aws_security_group.backend.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "udp"
  to_port           = 53
  description       = "DNS resolution"
}

resource "aws_vpc_security_group_egress_rule" "backend_dns_tcp" {
  security_group_id = aws_security_group.backend.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "tcp"
  to_port           = 53
  description       = "DNS fallback"
}

resource "aws_vpc_security_group_egress_rule" "backend_database" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.database.id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "PostgreSQL access"
}

resource "aws_vpc_security_group_egress_rule" "backend_cache" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.cache.id
  from_port                    = 6379
  ip_protocol                  = "tcp"
  to_port                      = 6379
  description                  = "TLS Redis access"
}

resource "aws_vpc_security_group_ingress_rule" "database_backend" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "PostgreSQL from backend instances only"
}

resource "aws_vpc_security_group_ingress_rule" "cache_backend" {
  security_group_id            = aws_security_group.cache.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 6379
  ip_protocol                  = "tcp"
  to_port                      = 6379
  description                  = "Redis from backend instances only"
}
