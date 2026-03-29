output "endpoint"      { value = aws_db_instance.main.endpoint }
output "address"       { value = aws_db_instance.main.address }
output "port"          { value = aws_db_instance.main.port }
output "db_name"       { value = aws_db_instance.main.db_name }
output "username"      {
  value     = aws_db_instance.main.username
  sensitive = true
}
output "database_url"  {
  value     = "postgresql+asyncpg://${aws_db_instance.main.username}:PASSWORD@${aws_db_instance.main.endpoint}/${aws_db_instance.main.db_name}"
  sensitive = true
}
