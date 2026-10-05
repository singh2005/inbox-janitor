data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  gmail_credentials_secret_arn = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:inbox-janitor/google-oauth-CBW5tq"arn:aws:secretsmanager:us-east-1:424006329489:secret:inbox-janitor/google-oauth-CBW5tq
}