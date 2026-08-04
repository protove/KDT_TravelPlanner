provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Environment = "dev"
      ManagedBy   = "Terraform"
      Phase       = "ec2-baseline"
      Project     = var.project_name
    }
  }
}
