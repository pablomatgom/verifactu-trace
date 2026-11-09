terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # The state is kept in S3, never in the repository. `use_lockfile` locks it with a lock
  # object in the same bucket, so two runs cannot change it at the same time.
  # The credentials are not here: Terraform reads them from the AWS profile
  # (`AWS_PROFILE=verifactu`).
  backend "s3" {
    bucket       = "verifactu-trace-tfstate-529470780070"
    key          = "verifactu-trace/terraform.tfstate"
    region       = "eu-north-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}
