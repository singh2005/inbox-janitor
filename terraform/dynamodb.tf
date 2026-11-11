resource "aws_dynamodb_table" "multitenant_rules" {
  name         = "inbox-janitor-multitenant-rules-tf"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "ttl_timestamp"
    enabled        = true
  }

  tags = {
    Environment = "production"
    Engine      = "multi-tenant"
  }
}

# Seed/Manage Canary Tenant List via Terraform
resource "aws_dynamodb_table_item" "canary_tenants_config" {
  table_name = aws_dynamodb_table.multitenant_rules.name
  hash_key   = aws_dynamodb_table.multitenant_rules.hash_key
  range_key  = aws_dynamodb_table.multitenant_rules.range_key

  item = jsonencode({
    PK      = { S = "CONFIG" }
    SK      = { S = "CANARY_TENANTS" }
    tenants = { L = [for email in local.canary_tenants : { S = email }] }
  })
}