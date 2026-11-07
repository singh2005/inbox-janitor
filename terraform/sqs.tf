resource "aws_sqs_queue" "ingress_dlq" {
  name                        = "inbox-janitor-ingress-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}

resource "aws_sqs_queue" "ingress_queue" {
  name                        = "inbox-janitor-ingress-queue.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 30

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingress_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_event_source_mapping" "ingress_sqs_to_router" {
  event_source_arn        = aws_sqs_queue.ingress_queue.arn
  function_name           = aws_lambda_function.router_engine.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_sqs_queue" "enforce_canary_dlq" {
  name                        = "inbox-janitor-enforce-canary-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}

resource "aws_sqs_queue" "enforce_canary_queue" {
  name                        = "inbox-janitor-enforce-canary-queue.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 360

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.enforce_canary_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_event_source_mapping" "sqs_to_enforce_canary" {
  event_source_arn        = aws_sqs_queue.enforce_canary_queue.arn
  function_name           = aws_lambda_alias.enforce_canary.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_sqs_queue" "enforce_prod_dlq" {
  name                        = "inbox-janitor-enforce-prod-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}

resource "aws_sqs_queue" "enforce_prod_queue" {
  name                        = "inbox-janitor-enforce-prod-queue.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 360

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.enforce_prod_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_event_source_mapping" "sqs_to_enforce_prod" {
  event_source_arn        = aws_sqs_queue.enforce_prod_queue.arn
  function_name           = aws_lambda_alias.enforce_prod.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}