output "volume_id" {
  description = "Identifier of the volume with the data of PostgreSQL, for the compute layer to attach it."
  value       = aws_ebs_volume.postgres_data.id
}
