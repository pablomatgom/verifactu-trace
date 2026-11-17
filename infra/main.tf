locals {
  # Applied to every resource that supports tags, to know what is ours and who manages it.
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

# Reads which account the credentials belong to. It creates nothing: it only proves that
# Terraform can talk to AWS.
data "aws_caller_identity" "current" {}

# The network: the VPC, its subnets, the routing and the security groups. The storage and
# compute layers are added as modules too, and use the identifiers that this one returns.
module "network" {
  source = "./modules/network"

  project_name            = var.project_name
  app_ports               = var.app_ports
  app_allowed_cidr_blocks = var.app_allowed_cidr_blocks
}

# The disk with the data of PostgreSQL, in the zone of the network so the instance can use it.
module "storage" {
  source = "./modules/storage"

  project_name      = var.project_name
  availability_zone = module.network.availability_zone
  size_gb           = var.data_volume_size_gb
}

# The instance that runs the system: it installs Docker, mounts the disk and starts the
# containers from the images published in GHCR.
module "compute" {
  source = "./modules/compute"

  project_name      = var.project_name
  aws_region        = var.aws_region
  subnet_id         = module.network.public_subnet_id
  security_group_id = module.network.compute_security_group_id
  volume_id         = module.storage.volume_id
  db_password       = var.db_password
  instance_type     = var.instance_type
  image_tag         = var.image_tag
}
