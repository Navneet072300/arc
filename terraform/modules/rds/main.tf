# ── Subnet Group ─────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "main" {
  name        = "${var.cluster_name}-rds-subnet-group"
  subnet_ids  = var.private_subnet_ids
  description = "Arc control-plane DB subnet group"
}

# ── Security Group ────────────────────────────────────────────────────────────

resource "aws_security_group" "rds" {
  name        = "${var.cluster_name}-rds-sg"
  description = "Allow PostgreSQL access from EKS nodes"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.node_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.cluster_name}-rds-sg" }
}

# ── Parameter Group ───────────────────────────────────────────────────────────

resource "aws_db_parameter_group" "main" {
  name        = "${var.cluster_name}-pg${var.postgres_version}"
  family      = "postgres${var.postgres_version}"
  description = "Arc control-plane DB parameters"

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"   # log queries > 1 s
  }

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
}

# ── RDS Instance ──────────────────────────────────────────────────────────────

resource "aws_db_instance" "main" {
  identifier        = "${var.cluster_name}-control-plane"
  engine            = "postgres"
  engine_version    = var.postgres_version
  instance_class    = var.instance_class
  db_name           = var.db_name
  username          = var.username
  password          = var.password
  port              = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.main.name

  allocated_storage     = var.storage_gb
  max_allocated_storage = var.max_storage_gb > 0 ? var.max_storage_gb : null
  storage_type          = "gp3"
  storage_encrypted     = true

  multi_az               = var.multi_az
  publicly_accessible    = false
  deletion_protection    = true
  skip_final_snapshot    = false
  final_snapshot_identifier = "${var.cluster_name}-final-snapshot"

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  performance_insights_enabled = true

  tags = { Name = "${var.cluster_name}-control-plane" }

  lifecycle {
    prevent_destroy = true
  }
}
