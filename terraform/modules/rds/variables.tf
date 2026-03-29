variable "cluster_name"          { type = string }
variable "vpc_id"                { type = string }
variable "private_subnet_ids"    { type = list(string) }
variable "node_security_group_id" { type = string }
variable "instance_class"        { type = string }
variable "postgres_version"      { type = string }
variable "db_name"               { type = string }
variable "username"              {
  type      = string
  sensitive = true
}
variable "password"              {
  type      = string
  sensitive = true
}
variable "multi_az"              { type = bool }
variable "storage_gb"            { type = number }
variable "max_storage_gb"        { type = number }
