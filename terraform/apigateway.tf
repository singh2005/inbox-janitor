# 1. AWS HTTP API Gateway Instance
resource "aws_apigatewayv2_api" "ingest_api" {
  name          = "inbox-janitor-webhook-tf"
  protocol_type = "HTTP"
  description   = "HTTP API gateway for Gmail Pub/Sub push webhooks"
}

# 2. Stage with Default Throttling (Rate/Burst limits applied to the gateway)
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.ingest_api.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 2 # Steady state RPS limit
    throttling_burst_limit = 4 # Burst request bucket limit
  }
}

# 3. Native JWT Authorizer backed by Google OIDC Issuer
resource "aws_apigatewayv2_authorizer" "gcp_pubsub_jwt" {
  api_id           = aws_apigatewayv2_api.ingest_api.id
  authorizer_type  = "JWT"
  name             = "gcp-pubsub-jwt-authorizer"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    # Standard Google OIDC issuer
    issuer = "https://accounts.google.com"

    # Validates that JWT 'aud' matches the push endpoint target
    audience = ["${aws_apigatewayv2_api.ingest_api.api_endpoint}/gmail-event"]
  }
}

# 4. SQS Proxy Integration (Direct push from API Gateway into SQS FIFO)
resource "aws_apigatewayv2_integration" "sqs_ingress_integration" {
  api_id              = aws_apigatewayv2_api.ingest_api.id
  integration_type    = "AWS_PROXY"
  integration_subtype = "SQS-SendMessage"
  credentials_arn     = aws_iam_role.apigw_sqs_role.arn

  request_parameters = {
    QueueUrl               = aws_sqs_queue.ingress_queue.url
    MessageBody            = "$request.body"
    MessageGroupId         = "gcp-pubsub-webhook"
    MessageDeduplicationId = "$context.requestId"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# 5. Secured Route linked directly to the JWT Authorizer
resource "aws_apigatewayv2_route" "post_gmail_event_route" {
  api_id             = aws_apigatewayv2_api.ingest_api.id
  route_key          = "POST /gmail-event"
  target             = "integrations/${aws_apigatewayv2_integration.sqs_ingress_integration.id}"
  
  # Connect JWT Authorization
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.gcp_pubsub_jwt.id
}

# AWS Outputs
output "api_gateway_endpoint" {
  value       = "${aws_apigatewayv2_api.ingest_api.api_endpoint}/gmail-event"
  description = "Public HTTP POST endpoint URL for GCP Pub/Sub push subscription"
}
