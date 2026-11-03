resource "aws_apigatewayv2_api" "ingest_api" {
  name          = "inbox-janitor-webhook-tf"
  protocol_type = "HTTP"
  description   = "HTTP API gateway for Gmail Pub/Sub push webhooks"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.ingest_api.id
  name        = "$default"
  auto_deploy = true
}

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

resource "aws_apigatewayv2_route" "post_gmail_event_route" {
  api_id    = aws_apigatewayv2_api.ingest_api.id
  route_key = "POST /gmail-event"
  target    = "integrations/${aws_apigatewayv2_integration.sqs_ingress_integration.id}"
}

output "api_gateway_endpoint" {
  value       = "${aws_apigatewayv2_api.ingest_api.api_endpoint}/gmail-event"
  description = "Public HTTP POST endpoint URL for GCP Pub/Sub push subscription"
}