resource "aws_dynamodb_table" "raw_email_logs" {
  name           = "inbox-janitor-raw-email-logs-tf"
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "sender_address"
  range_key      = "timestamp_message_id"

  attribute {
    name = "sender_address"
    type = "S"
  }

  attribute {
    name = "timestamp_message_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "active_routing_rules" {
  name           = "inbox-janitor-active-routing-rules-tf"
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "sender_address"

  attribute {
    name = "sender_address"
    type = "S"
  }
}
