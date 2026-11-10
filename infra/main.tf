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
  admin_cidr_blocks       = var.admin_cidr_blocks
}
