locals {
  # Applied to every resource that supports tags, to know what is ours and who manages it.
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

# Reads which account the credentials belong to. It creates nothing: it only proves that
# Terraform can talk to AWS. The network, storage and compute layers are added as modules.
data "aws_caller_identity" "current" {}
