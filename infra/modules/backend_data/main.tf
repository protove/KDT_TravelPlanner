locals {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-database"
  subnet_ids = var.data_subnet_ids
  tags       = var.tags
}

resource "aws_db_instance" "this" {
  identifier = "${local.name}-postgres"

  allocated_storage           = 20
  max_allocated_storage       = 100
  storage_type                = "gp3"
  storage_encrypted           = true
  engine                      = "postgres"
  engine_version              = var.postgres_engine_version
  instance_class              = var.db_instance_class
  db_name                     = var.database_name
  username                    = var.database_username
  manage_master_user_password = true
  port                        = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.database_security_group_id]
  publicly_accessible    = false
  multi_az               = false

  auto_minor_version_upgrade   = false
  apply_immediately            = true
  backup_retention_period      = 1
  copy_tags_to_snapshot        = true
  deletion_protection          = false
  performance_insights_enabled = false
  skip_final_snapshot          = true

  tags = var.tags
}

resource "random_password" "redis_auth" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "redis" {
  name                    = "${local.name}/redis/auth"
  description             = "Generated Redis authentication token for the ephemeral ${var.environment} runtime"
  recovery_window_in_days = 0
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "redis" {
  secret_id = aws_secretsmanager_secret.redis.id
  secret_string = jsonencode({
    password = random_password.redis_auth.result
  })
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.name}-cache"
  subnet_ids = var.data_subnet_ids
  tags       = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.name}-redis"
  description          = "${var.environment} TravelPlanner Redis OSS cache"

  engine             = "redis"
  engine_version     = var.redis_engine_version
  node_type          = var.cache_node_type
  num_cache_clusters = 1
  port               = 6379

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"
  auth_token                 = random_password.redis_auth.result
  auth_token_update_strategy = "SET"

  automatic_failover_enabled = false
  multi_az_enabled           = false
  apply_immediately          = true
  snapshot_retention_limit   = 0

  security_group_ids = [var.cache_security_group_id]
  subnet_group_name  = aws_elasticache_subnet_group.this.name

  tags = var.tags
}
