data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# ── VPC ──────────────────────────────────────────────────────────────────────

module "vpc" {
  source = "./modules/vpc"

  cluster_name       = var.cluster_name
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
}

# ── EKS ──────────────────────────────────────────────────────────────────────

module "eks" {
  source = "./modules/eks"

  cluster_name       = var.cluster_name
  kubernetes_version = var.kubernetes_version
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  node_instance_type = var.node_instance_type
  node_desired_size  = var.node_desired_size
  node_min_size      = var.node_min_size
  node_max_size      = var.node_max_size
  node_disk_size_gb  = var.node_disk_size_gb
}

# ── RDS ───────────────────────────────────────────────────────────────────────

module "rds" {
  source = "./modules/rds"

  cluster_name           = var.cluster_name
  vpc_id                 = module.vpc.vpc_id
  private_subnet_ids     = module.vpc.private_subnet_ids
  node_security_group_id = module.eks.node_security_group_id

  instance_class   = var.rds_instance_class
  postgres_version = var.rds_postgres_version
  db_name          = var.rds_db_name
  username         = var.rds_username
  password         = var.rds_password
  multi_az         = var.rds_multi_az
  storage_gb       = var.rds_storage_gb
  max_storage_gb   = var.rds_max_storage_gb
}

# ── ECR Repository ────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "arc_api" {
  name                 = "arc-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "arc_api" {
  repository = aws_ecr_repository.arc_api.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last N images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_image_retention_count
        }
        action = { type = "expire" }
      }
    ]
  })
}

# ── Kubeconfig helper ─────────────────────────────────────────────────────────

resource "local_file" "kubeconfig_cmd" {
  filename        = "${path.module}/rendered/update-kubeconfig.sh"
  file_permission = "0755"
  content         = <<-SH
    #!/bin/bash
    aws eks update-kubeconfig \
      --region ${data.aws_region.current.name} \
      --name ${module.eks.cluster_name} \
      --alias ${module.eks.cluster_name}
  SH
}
