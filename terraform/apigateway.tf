# 1. HTTP API Gateway Instance
resource "aws_apigatewayv2_api" "ingest_api" {
  name          = "inbox-janitor-webhook-tf"
  protocol_type = "HTTP"
  description   = "HTTP API gateway for Gmail Pub/Sub push webhooks"
}

# 2. $default Auto-deploying Stage
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.ingest_api.id
  name        = "$default"
  auto_deploy = true
}

# 3. Lambda Integration targeting CANARY Alias
resource "aws_apigatewayv2_integration" "lambda_ingest_integration" {
  api_id                 = aws_apigatewayv2_api.ingest_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.ingest_canary.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

# 4. Route POST /gmail-event to Lambda Integration
resource "aws_apigatewayv2_route" "post_gmail_event_route" {
  api_id    = aws_apigatewayv2_api.ingest_api.id
  route_key = "POST /gmail-event"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_ingest_integration.id}"
}

# 5. Grant API Gateway permission to invoke the CANARY Lambda Alias
resource "aws_lambda_permission" "api_gw_canary_permission" {
  statement_id  = "AllowAPIGatewayInvokeIngestCanary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_engine.function_name
  qualifier     = aws_lambda_alias.ingest_canary.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ingest_api.execution_arn}/*/*/gmail-event"
}

# 6. Grant API Gateway permission to invoke the PROD Lambda Alias (For promotion phase)
resource "aws_lambda_permission" "api_gw_prod_permission" {
  statement_id  = "AllowAPIGatewayInvokeIngestProd"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_engine.function_name
  qualifier     = aws_lambda_alias.ingest_prod.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ingest_api.execution_arn}/*/*/gmail-event"
}

output "api_gateway_endpoint" {
  value       = "${aws_apigatewayv2_api.ingest_api.api_endpoint}/gmail-event"
  description = "Public HTTP POST endpoint URL for GCP Pub/Sub push subscription"
}