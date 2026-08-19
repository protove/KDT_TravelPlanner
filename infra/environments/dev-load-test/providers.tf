provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Environment = "dev"
      ManagedBy   = "Terraform"
      Phase       = "load-test"
      Project     = var.project_name
      Stack       = "dev-load-test"
    }
  }
}
