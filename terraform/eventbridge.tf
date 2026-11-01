# 1. Custom Event Bus
resource "aws_cloudwatch_event_bus" "inbox_janitor_bus" {
  name = "inbox-janitor-event-bus"
}

# 2. Rule for CANARY Tenants (Matches exact email in JSON body)
resource "aws_cloudwatch_event_rule" "canary_rule" {
  name           = "inbox-janitor-canary-rule"
  description    = "Routes webhooks from canary tenants to ingest:CANARY"
  event_bus_name = aws_cloudwatch_event_bus.inbox_janitor_bus.name

  event_pattern = jsonencode({
    source = ["gcp.pubsub"]
    detail = {
      # EventBridge automatically unwraps nested JSON attributes in the body
      emailAddress = local.canary_tenants
    }
  })
}

# 3. Rule for PROD Tenants (Matches all non-canary emails)
resource "aws_cloudwatch_event_rule" "prod_rule" {
  name           = "inbox-janitor-prod-rule"
  description    = "Routes all non-canary webhooks to ingest:PROD"
  event_bus_name = aws_cloudwatch_event_bus.inbox_janitor_bus.name

  event_pattern = jsonencode({
    source = ["gcp.pubsub"]
    detail = {
      emailAddress = [{ "anything-but" = local.canary_tenants }]
    }
  })
}

# 4. Target for CANARY Rule -> ingest_canary Alias
resource "aws_cloudwatch_event_target" "canary_target" {
  rule           = aws_cloudwatch_event_rule.canary_rule.name
  event_bus_name = aws_cloudwatch_event_bus.inbox_janitor_bus.name
  arn            = aws_lambda_alias.ingest_canary.arn
}

# 5. Target for PROD Rule -> ingest_prod Alias
resource "aws_cloudwatch_event_target" "prod_target" {
  rule           = aws_cloudwatch_event_rule.prod_rule.name
  event_bus_name = aws_cloudwatch_event_bus.inbox_janitor_bus.name
  arn            = aws_lambda_alias.ingest_prod.arn
}

# 6. Lambda Permissions for EventBridge Invocation
resource "aws_lambda_permission" "allow_eventbridge_canary" {
  statement_id  = "AllowEventBridgeInvokeIngestCanary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_engine.function_name
  qualifier     = aws_lambda_alias.ingest_canary.name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.canary_rule.arn
}

resource "aws_lambda_permission" "allow_eventbridge_prod" {
  statement_id  = "AllowEventBridgeInvokeIngestProd"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_engine.function_name
  qualifier     = aws_lambda_alias.ingest_prod.name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.prod_rule.arn
}