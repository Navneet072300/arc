variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (prod | staging)"
  type        = string
  default     = "prod"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "arc-cluster"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.31"
}

# ── VPC ──────────────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "AZs to spread resources across (leave empty to auto-select 3)"
  type        = list(string)
  default     = []
}

# ── EKS Node Group ───────────────────────────────────────────────────────────

variable "node_instance_type" {
  description = "EC2 instance type for EKS worker nodes"
  type        = string
  default     = "t3.medium"
}

variable "node_desired_size" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 3
}

variable "node_min_size" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum number of worker nodes"
  type        = number
  default     = 10
}

variable "node_disk_size_gb" {
  description = "Root volume size (GB) for each worker node"
  type        = number
  default     = 50
}

# ── RDS (control-plane DB) ───────────────────────────────────────────────────

variable "rds_instance_class" {
  description = "RDS instance type for the Arc control-plane database"
  type        = string
  default     = "db.t3.micro"
}

variable "rds_postgres_version" {
  description = "PostgreSQL major version for RDS"
  type        = string
  default     = "16"
}

variable "rds_db_name" {
  description = "Initial database name"
  type        = string
  default     = "arc_control"
}

variable "rds_username" {
  description = "Master username for RDS"
  type        = string
  default     = "arcadmin"
  sensitive   = true
}

variable "rds_password" {
  description = "Master password for RDS (use secrets manager in production)"
  type        = string
  sensitive   = true
}

variable "rds_multi_az" {
  description = "Enable Multi-AZ for RDS (recommended for production)"
  type        = bool
  default     = false
}

variable "rds_storage_gb" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_max_storage_gb" {
  description = "Maximum storage for autoscaling (0 = disabled)"
  type        = number
  default     = 100
}

# ── ECR ──────────────────────────────────────────────────────────────────────

variable "ecr_image_retention_count" {
  description = "Number of Arc API images to keep in ECR"
  type        = number
  default     = 10
}
