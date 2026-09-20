data "aws_secretsmanager_secret" "gmail_credentials" {
  name = "inbox-janitor/google-oauth"
}