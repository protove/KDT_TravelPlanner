locals {
  state_bucket_name = "${var.project_name}-tfstate-${var.aws_account_id}-${var.aws_region}"
}

module "terraform_state_backend" {
  source = "../modules/terraform_state_backend"

  bucket_name = local.state_bucket_name
  state_keys = [
    "dev/terraform.tfstate",
    "dev-load-test/terraform.tfstate",
    "dev-runtime/terraform.tfstate",
  ]
}
