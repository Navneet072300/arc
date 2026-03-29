variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "db_name" {
  type    = string
  default = "arc_control"
}

variable "username" {
  type      = string
  sensitive = true
}

variable "password" {
  type      = string
  sensitive = true
}

# Your public IP(s) — only these can reach the DB
# Find yours: curl ifconfig.me
variable "allowed_cidrs" {
  type    = list(string)
  default = []  # e.g. ["203.0.113.42/32"]
}
