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

  # Primary Partition Key
  attribute {
    name = "sender_address"
    type = "S"
  }

  # GSI Partition Key
  attribute {
    name = "entity_type"
    type = "S"
  }

  # GSI Sort Key
  attribute {
    name = "trashed_count"
    type = "N"
  }

  global_secondary_index {
    name            = "TopTrashedSendersIndex"
    hash_key        = "entity_type"
    range_key       = "trashed_count"
    projection_type = "ALL"
  }
}
