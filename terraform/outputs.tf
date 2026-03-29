output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint"
  value       = module.eks.cluster_endpoint
}

output "kubeconfig_command" {
  description = "Run this to configure kubectl"
  value       = "aws eks update-kubeconfig --region ${data.aws_region.current.name} --name ${module.eks.cluster_name}"
}

output "ecr_repository_url" {
  description = "ECR URL to push the Arc API image to"
  value       = aws_ecr_repository.arc_api.repository_url
}

output "ecr_push_commands" {
  description = "Commands to build and push the Arc API image"
  value       = <<-EOT
    aws ecr get-login-password --region ${data.aws_region.current.name} \
      | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com

    docker build -t arc-api .
    docker tag arc-api:latest ${aws_ecr_repository.arc_api.repository_url}:latest
    docker push ${aws_ecr_repository.arc_api.repository_url}:latest
  EOT
}

output "rds_endpoint" {
  description = "RDS control-plane database endpoint"
  value       = module.rds.endpoint
}

output "rds_database_url" {
  description = "DATABASE_URL for Arc API (replace PASSWORD)"
  value       = module.rds.database_url
  sensitive   = true
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}
