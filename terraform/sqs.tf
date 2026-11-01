# --- CANARY PIPELINE QUEUES ---
resource "aws_sqs_queue" "enforce_dlq_canary" {
  name                        = "inbox-janitor-enforce-dlq-canary.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}

resource "aws_sqs_queue" "enforce_queue_canary" {
  name                        = "inbox-janitor-enforce-queue-canary.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 360

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.enforce_dlq_canary.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_event_source_mapping" "sqs_to_enforce_canary" {
  event_source_arn        = aws_sqs_queue.enforce_queue_canary.arn
  function_name           = aws_lambda_alias.enforce_canary.arn # Target CANARY Alias
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}

# --- PROD PIPELINE QUEUES ---
resource "aws_sqs_queue" "enforce_dlq_prod" {
  name                        = "inbox-janitor-enforce-dlq-prod.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}

resource "aws_sqs_queue" "enforce_queue_prod" {
  name                        = "inbox-janitor-enforce-queue-prod.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 360

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.enforce_dlq_prod.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_event_source_mapping" "sqs_to_enforce_prod" {
  event_source_arn        = aws_sqs_queue.enforce_queue_prod.arn
  function_name           = aws_lambda_alias.enforce_prod.arn # Target PROD Alias
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}