# 1. Dead-Letter Queue (FIFO)
resource "aws_sqs_queue" "enforce_dlq" {
  name                        = "inbox-janitor-enforce-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}

# 2. Main Enforce Work Queue (FIFO)
resource "aws_sqs_queue" "enforce_queue" {
  name                        = "inbox-janitor-enforce-queue.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 360 # Must be >= enforce_lambda timeout

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.enforce_dlq.arn
    maxReceiveCount     = 3
  })
}

# 3. SQS Event Source Mapping to Enforce Lambda
resource "aws_lambda_event_source_mapping" "sqs_to_enforce" {
  event_source_arn        = aws_sqs_queue.enforce_queue.arn
  function_name           = aws_lambda_function.enforce_engine.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}