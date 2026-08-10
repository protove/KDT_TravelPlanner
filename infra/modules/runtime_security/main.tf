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

resource "aws_security_group" "monitoring" {
  name_prefix            = "${local.name}-monitoring-"
  description            = "Private Prometheus, Loki and Grafana for the monitoring EC2"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = merge(var.tags, { Name = "${local.name}-monitoring-sg" })
}

resource "aws_vpc_security_group_egress_rule" "backend_monitoring_loki" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.monitoring.id
  from_port                    = 3100
  ip_protocol                  = "tcp"
  to_port                      = 3100
  description                  = "Alloy pushes logs to the central Loki"
}

resource "aws_vpc_security_group_ingress_rule" "backend_monitoring_scrape" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.monitoring.id
  from_port                    = 9091
  ip_protocol                  = "tcp"
  to_port                      = 9091
  description                  = "Prometheus scrapes backend actuator metrics"
}

resource "aws_vpc_security_group_ingress_rule" "backend_monitoring_alloy" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.monitoring.id
  from_port                    = 12345
  ip_protocol                  = "tcp"
  to_port                      = 12345
  description                  = "Prometheus scrapes Alloy metrics"
}

resource "aws_vpc_security_group_ingress_rule" "monitoring_loki" {
  security_group_id            = aws_security_group.monitoring.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 3100
  ip_protocol                  = "tcp"
  to_port                      = 3100
  description                  = "Receive log pushes from backend Alloy instances only"
}

resource "aws_vpc_security_group_egress_rule" "monitoring_scrape" {
  security_group_id            = aws_security_group.monitoring.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 9091
  ip_protocol                  = "tcp"
  to_port                      = 9091
  description                  = "Scrape backend actuator metrics"
}

resource "aws_vpc_security_group_egress_rule" "monitoring_scrape_alloy" {
  security_group_id            = aws_security_group.monitoring.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 12345
  ip_protocol                  = "tcp"
  to_port                      = 12345
  description                  = "Scrape Alloy metrics from backend instances"
}

resource "aws_vpc_security_group_egress_rule" "monitoring_https" {
  security_group_id = aws_security_group.monitoring.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
  description       = "CloudWatch API, SSM and other AWS endpoints"
}

resource "aws_vpc_security_group_egress_rule" "monitoring_dns_udp" {
  security_group_id = aws_security_group.monitoring.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "udp"
  to_port           = 53
  description       = "DNS resolution"
}

resource "aws_vpc_security_group_egress_rule" "monitoring_dns_tcp" {
  security_group_id = aws_security_group.monitoring.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "tcp"
  to_port           = 53
  description       = "DNS fallback"
}

# ── Load Runner (SSM 전용, inbound 없음) ────────────────────────
# k6는 공개 ALB DNS로 HTTPS를 쏘므로 ALB SG를 참조하지 않고 일반 443
# egress를 쓴다 (backend_https/monitoring_https와 동일한 이유).
# RDS/Redis는 seed·cleanup 스크립트가 직접 접속해야 하므로 SG 참조로
# 좁힌다. Monitoring 연결은 D-002(remote-write 방식)가 정해지지 않아
# 이 이슈에서 규칙을 추가하지 않는다 (aws-load-test-handoff/decisions/OPEN_DECISIONS.md).
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
  referenced_security_group_id = aws_security_group.database.id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "Seed and cleanup synthetic load-test data directly in PostgreSQL"
}

resource "aws_vpc_security_group_ingress_rule" "database_load_runner" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.load_runner.id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "PostgreSQL from the Load Runner for seed/cleanup only"
}

resource "aws_vpc_security_group_egress_rule" "load_runner_cache" {
  security_group_id            = aws_security_group.load_runner.id
  referenced_security_group_id = aws_security_group.cache.id
  from_port                    = 6379
  ip_protocol                  = "tcp"
  to_port                      = 6379
  description                  = "Seed and cleanup synthetic refresh-token data directly in Redis"
}

resource "aws_vpc_security_group_ingress_rule" "cache_load_runner" {
  security_group_id            = aws_security_group.cache.id
  referenced_security_group_id = aws_security_group.load_runner.id
  from_port                    = 6379
  ip_protocol                  = "tcp"
  to_port                      = 6379
  description                  = "Redis from the Load Runner for seed/cleanup only"
}
