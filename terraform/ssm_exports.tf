resource "aws_ssm_parameter" "ingest_api_id" {
  name        = "/inbox-janitor/infra/ingest-api-id"
  description = "API Gateway ID for the ingest API"
  type        = "String"
  value       = aws_apigatewayv2_api.ingest_api.id
}

resource "aws_ssm_parameter" "ingest_api_endpoint" {
  name        = "/inbox-janitor/infra/ingest-api-endpoint"
  description = "API Gateway endpoint URL for the ingest API"
  type        = "String"
  value       = aws_apigatewayv2_api.ingest_api.api_endpoint
}

resource "aws_ssm_parameter" "multitenant_rules_table_name" {
  name        = "/inbox-janitor/infra/multitenant-rules-table-name"
  description = "DynamoDB table name for multitenant rules"
  type        = "String"
  value       = aws_dynamodb_table.multitenant_rules.name
}

resource "aws_ssm_parameter" "gcp_pubsub_topic_id" {
  name        = "/inbox-janitor/infra/gcp-pubsub-topic"
  description = "Full GCP Pub/Sub topic resource ID for Gmail users.watch()"
  type        = "String"
  value       = google_pubsub_topic.gmail_push_topic.id
}