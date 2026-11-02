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

resource "aws_sqs_queue" "enforce_dlq" {
  name                        = "inbox-janitor-enforce-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}

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

# CANARY Event Source Mapping with Native Filter Criteria
resource "aws_lambda_event_source_mapping" "sqs_to_enforce_canary" {
  event_source_arn        = aws_sqs_queue.enforce_queue.arn
  function_name           = aws_lambda_alias.enforce_canary.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  filter_criteria {
    filter {
      pattern = jsonencode({
        body = {
          is_canary = [true]
        }
      })
    }
  }
}

# PROD Event Source Mapping with Native Filter Criteria
resource "aws_lambda_event_source_mapping" "sqs_to_enforce_prod" {
  event_source_arn        = aws_sqs_queue.enforce_queue.arn
  function_name           = aws_lambda_alias.enforce_prod.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  filter_criteria {
    filter {
      pattern = jsonencode({
        body = {
          is_canary = [{ "anything-but" = true }]
        }
      })
    }
  }
}