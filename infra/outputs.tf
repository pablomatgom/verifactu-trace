output "account_id" {
  description = "AWS account where the infrastructure is created."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "Region of the infrastructure."
  value       = var.aws_region
}

output "vpc_id" {
  description = "Identifier of the network."
  value       = module.network.vpc_id
}

output "public_subnet_id" {
  description = "Subnet of the compute instance."
  value       = module.network.public_subnet_id
}

output "private_subnet_id" {
  description = "Subnet without a route to the Internet."
  value       = module.network.private_subnet_id
}

output "compute_security_group_id" {
  description = "Security group of the compute instance."
  value       = module.network.compute_security_group_id
}

output "availability_zone" {
  description = "Zone of the subnets."
  value       = module.network.availability_zone
}
