output "rds_endpoint" {
  value = aws_db_instance.main.endpoint
}

output "database_url" {
  value     = "postgresql+asyncpg://${var.username}:${var.password}@${aws_db_instance.main.endpoint}/${var.db_name}"
  sensitive = true
}

output "env_line" {
  description = "Paste this into your .env file"
  value       = "DATABASE_URL=postgresql+asyncpg://${var.username}:${var.password}@${aws_db_instance.main.endpoint}/${var.db_name}"
  sensitive   = true
}
