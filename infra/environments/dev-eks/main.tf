locals {
  environment = "dev"
  name        = "${var.project_name}-${local.environment}"
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

  admin_principal_arns    = var.admin_principal_arns
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

# ── SSM 검증 bastion ────────────────────────────────────────────
# EKS 컨트롤 플레인이 기본적으로 완전 비공개(endpoint_public_access=false)라,
# 이 프로젝트의 다른 EC2들(backend_service, monitoring_ec2)과 동일하게 인바운드
# 포트 없이 SSM으로만 접속해서 그 안에서 kubectl을 검증한다. bastion 자체가
# private app subnet 안에 있으므로 별도 포트포워딩 없이 바로 private endpoint에
# 닿는다.
data "aws_ssm_parameter" "bastion_al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "bastion_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "bastion" {
  name               = "${local.name}-eks-bastion"
  assume_role_policy = data.aws_iam_policy_document.bastion_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "bastion_ssm" {
  role       = aws_iam_role.bastion.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "bastion" {
  name = "${local.name}-eks-bastion"
  role = aws_iam_role.bastion.name
  tags = local.common_tags
}

resource "aws_security_group" "bastion" {
  name_prefix            = "${local.name}-eks-bastion-"
  description            = "SSM-only EKS verification bastion; no inbound"
  vpc_id                 = data.terraform_remote_state.persistent.outputs.vpc_id
  revoke_rules_on_delete = true
  tags                   = merge(local.common_tags, { Name = "${local.name}-eks-bastion-sg" })
}

resource "aws_vpc_security_group_egress_rule" "bastion_https" {
  security_group_id = aws_security_group.bastion.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
  description       = "SSM and AWS API endpoints"
}

resource "aws_vpc_security_group_egress_rule" "bastion_dns_udp" {
  security_group_id = aws_security_group.bastion.id
  cidr_ipv4         = "${cidrhost(data.terraform_remote_state.persistent.outputs.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "udp"
  to_port           = 53
  description       = "DNS resolution"
}

resource "aws_vpc_security_group_egress_rule" "bastion_dns_tcp" {
  security_group_id = aws_security_group.bastion.id
  cidr_ipv4         = "${cidrhost(data.terraform_remote_state.persistent.outputs.vpc_cidr, 2)}/32"
  from_port         = 53
  ip_protocol       = "tcp"
  to_port           = 53
  description       = "DNS fallback"
}

# EKS's auto-created cluster security group has no rule allowing anything in
# by default; the bastion needs one explicit path to the private API port.
resource "aws_vpc_security_group_ingress_rule" "cluster_from_bastion" {
  security_group_id            = module.eks_cluster.cluster_security_group_id
  referenced_security_group_id = aws_security_group.bastion.id
  from_port                    = 443
  ip_protocol                  = "tcp"
  to_port                      = 443
  description                  = "kubectl from the SSM verification bastion only"
}

resource "aws_instance" "bastion" {
  ami                    = data.aws_ssm_parameter.bastion_al2023_ami.value
  instance_type          = "t3.micro"
  subnet_id              = data.terraform_remote_state.persistent.outputs.app_subnet_ids[0]
  iam_instance_profile   = aws_iam_instance_profile.bastion.name
  vpc_security_group_ids = [aws_security_group.bastion.id]

  associate_public_ip_address = false

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 1
    http_tokens                 = "required"
  }

  root_block_device {
    encrypted   = true
    volume_size = 8
    volume_type = "gp3"
  }

  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/templates/bastion-user-data.sh.tftpl", {
    aws_region      = var.aws_region
    kubectl_version = var.bastion_kubectl_version
  })

  tags = merge(local.common_tags, { Name = "${local.name}-eks-bastion" })
}
