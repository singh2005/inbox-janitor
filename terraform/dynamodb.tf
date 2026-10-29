resource "aws_dynamodb_table" "raw_email_logs" {
  name         = "inbox-janitor-raw-email-logs-tf"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sender_address"
  range_key    = "timestamp_message_id"

  attribute {
    name = "sender_address"
    type = "S"
  }

  attribute {
    name = "timestamp_message_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl_timestamp"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "active_routing_rules" {
  name         = "inbox-janitor-active-routing-rules-tf"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sender_address"

  attribute {
    name = "sender_address"
    type = "S"
  }
}

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