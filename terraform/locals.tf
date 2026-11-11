data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  canary_tenants = [
    "singh2005@gmail.com"
  ]
}