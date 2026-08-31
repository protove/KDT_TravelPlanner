locals {
  environment = "dev"
  common_tags = {
    Environment = local.environment
    Phase       = "load-test"
    Project     = var.project_name
    Stack       = "dev-load-test"
  }
}

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "persistent" {
  backend = "s3"

  config = {
    bucket       = var.state_bucket
    key          = var.persistent_state_key
    region       = var.aws_region
    use_lockfile = true
    encrypt      = true
  }
}

data "terraform_remote_state" "runtime" {
  backend = "s3"

  config = {
    bucket       = var.state_bucket
    key          = var.runtime_state_key
    region       = var.aws_region
    use_lockfile = true
    encrypt      = true
  }
}

module "load_test_security" {
  source = "../../modules/load_test_security"

  cache_security_group_id       = data.terraform_remote_state.runtime.outputs.cache_security_group_id
  database_security_group_id    = data.terraform_remote_state.runtime.outputs.database_security_group_id
  eks_cluster_security_group_id = try(data.terraform_remote_state.runtime.outputs.cluster_security_group_id, "")
  environment                   = local.environment
  project_name                  = var.project_name
  tags                          = local.common_tags
  vpc_cidr                      = data.terraform_remote_state.persistent.outputs.vpc_cidr
  vpc_id                        = data.terraform_remote_state.persistent.outputs.vpc_id
}

module "load_test_runner" {
  source = "../../modules/load_test_runner"

  app_subnet_id               = data.terraform_remote_state.persistent.outputs.app_subnet_ids[0]
  aws_region                  = var.aws_region
  botocore_version            = var.load_runner_botocore_version
  environment                 = local.environment
  evidence_bucket_name        = "${var.project_name}-${local.environment}-load-test-evidence-${data.aws_caller_identity.current.account_id}"
  instance_type               = var.load_runner_instance_type
  root_volume_size_gib        = var.load_runner_root_volume_size_gib
  k6_image_reference          = var.k6_image_reference
  google_mock_image_reference = var.google_mock_image_reference
  project_name                = var.project_name
  runner_security_group_id    = module.load_test_security.security_group_id
  secrets_arns = [
    var.test_db_secret_arn,
  ]
  redis_iam_auth_arns = [
    data.terraform_remote_state.runtime.outputs.redis_load_test_user_arn,
    data.terraform_remote_state.runtime.outputs.redis_replication_group_arn,
  ]
  eks_observation_stack = var.runtime_state_key == "dev-eks/terraform.tfstate" ? "dev-eks" : ""
  source_commit_sha     = var.load_runner_source_commit_sha
  tags                  = local.common_tags

  # The security-group ID alone depends only on the SG resource. Wait for all
  # HTTPS, DNS, PostgreSQL and Redis rules before user data starts package,
  # source and image downloads on the Runner.
  depends_on = [module.load_test_security]
}

# Exactly one private A record is created only when this disposable State is
# pointed at dev-eks.  The Runner private IP is the mock's stable endpoint;
# no public hosted zone, alias, or EKS mock workload is introduced.
resource "aws_route53_record" "google_api_mock" {
  count = var.runtime_state_key == "dev-eks/terraform.tfstate" ? 1 : 0

  zone_id = data.terraform_remote_state.runtime.outputs.private_zone_id
  name    = "google-api-mock"
  type    = "A"
  ttl     = 30
  records = [module.load_test_runner.private_ip]
}
