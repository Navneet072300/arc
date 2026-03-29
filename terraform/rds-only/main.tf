terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = "arc"
      ManagedBy = "terraform"
    }
  }
}

# ── Use the default VPC + subnets ────────────────────────────────────────────
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ── Security Group: restrict to your IP + optional CIDR ──────────────────────
resource "aws_security_group" "rds" {
  name        = "arc-rds-sg"
  description = "Arc control-plane RDS access"
  vpc_id      = data.aws_vpc.default.id

  dynamic "ingress" {
    for_each = var.allowed_cidrs
    content {
      description = "PostgreSQL from allowed CIDR"
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── Subnet Group ─────────────────────────────────────────────────────────────
resource "aws_db_subnet_group" "main" {
  name       = "arc-rds-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
}

# ── Parameter Group ───────────────────────────────────────────────────────────
resource "aws_db_parameter_group" "main" {
  name   = "arc-pg16"
  family = "postgres16"
}

# ── RDS Instance ──────────────────────────────────────────────────────────────
resource "aws_db_instance" "main" {
  identifier        = "arc-control-plane"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = var.instance_class
  db_name           = var.db_name
  username          = var.username
  password          = var.password
  port              = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.main.name

  # Publicly accessible so Arc can reach it from minikube/VPS
  # Lock down allowed_cidrs to your IP only
  publicly_accessible = true

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  backup_retention_period   = 7
  skip_final_snapshot       = false
  final_snapshot_identifier = "arc-final"
  deletion_protection       = true

  tags = { Name = "arc-control-plane" }
}
