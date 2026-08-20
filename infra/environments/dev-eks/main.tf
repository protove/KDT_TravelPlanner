locals {
  environment = "dev"
  common_tags = {
    Environment = local.environment
    Phase       = "eks-baseline"
    Project     = var.project_name
    Stack       = "dev-eks"
  }
}

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

# Deliberately independent of dev-runtime (SCRUM-21 precedent): the EKS
# cluster itself must be creatable and destroyable regardless of whether the
# EC2 runtime is up. RDS/Redis security-group wiring is SCRUM-11 scope.
module "eks_cluster" {
  source = "../../modules/eks_cluster"

  environment             = local.environment
  endpoint_private_access = true
  endpoint_public_access  = var.endpoint_public_access
  kubernetes_version      = var.kubernetes_version
  node_desired_size       = var.node_desired_size
  node_instance_types     = var.node_instance_types
  node_max_size           = var.node_max_size
  node_min_size           = var.node_min_size
  project_name            = var.project_name
  public_access_cidrs     = var.public_access_cidrs
  subnet_ids              = data.terraform_remote_state.persistent.outputs.app_subnet_ids
  tags                    = local.common_tags
}
