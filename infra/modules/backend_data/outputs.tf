output "database_address" {
  description = "RDS PostgreSQL hostname."
  value       = aws_db_instance.this.address
}

output "database_master_secret_arn" {
  description = "RDS-managed master credential secret ARN."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "database_name" {
  description = "Initial PostgreSQL database name."
  value       = aws_db_instance.this.db_name
}

output "database_port" {
  description = "RDS PostgreSQL port."
  value       = aws_db_instance.this.port
}

output "redis_auth_secret_arn" {
  description = "Secrets Manager ARN containing the generated Redis password."
  value       = aws_secretsmanager_secret.redis.arn
}

output "redis_primary_endpoint" {
  description = "Redis primary endpoint hostname."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "redis_port" {
  description = "Redis TLS port."
  value       = aws_elasticache_replication_group.this.port
}
