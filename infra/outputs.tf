output "account_id" {
  description = "AWS account where the infrastructure is created."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "Region of the infrastructure."
  value       = var.aws_region
}
