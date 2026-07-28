# State bucket was bootstrapped from local State and migrated to the S3 backend.
# Backend credentials remain outside Terraform configuration and come from AWS_PROFILE.
terraform {
  backend "s3" {}
}
