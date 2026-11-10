output "vpc_id" {
  description = "Identifier of the network."
  value       = aws_vpc.main.id
}

output "public_subnet_id" {
  description = "Subnet of the compute instance."
  value       = aws_subnet.public.id
}

output "private_subnet_id" {
  description = "Subnet without a route to the Internet."
  value       = aws_subnet.private.id
}

output "compute_security_group_id" {
  description = "Security group of the compute instance."
  value       = aws_security_group.compute.id
}

output "availability_zone" {
  description = "Zone of both subnets. The disk of the database has to be created in it."
  value       = local.az
}
