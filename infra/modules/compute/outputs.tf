output "instance_id" {
  description = "Identifier of the instance. It is what a Systems Manager session needs."
  value       = aws_instance.app.id
}

output "public_ip" {
  description = "Public address of the instance. It changes if the instance is stopped and started."
  value       = aws_instance.app.public_ip
}
