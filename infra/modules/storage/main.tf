# The disk that keeps the data of PostgreSQL. It is not part of the instance, so the data
# survive if the instance is stopped, restarted or replaced. The compute layer attaches it:
# it is the one that knows the instance.
#
# `terraform destroy` deletes it, and the data with it. That is intended for a lab that is
# shut down after every session; no final snapshot is taken, so nothing is left costing money.
resource "aws_ebs_volume" "postgres_data" {
  availability_zone = var.availability_zone
  size              = var.size_gb
  type              = "gp3"

  # Encrypted at rest with the default key that AWS manages for EBS.
  encrypted = true

  tags = { Name = "${var.project_name}-postgres-data" }
}
