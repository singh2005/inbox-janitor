data "archive_file" "policy_evaluator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src/policy_evaluator"
  output_path = "${path.module}/builds/policy_evaluator.zip"
}

resource "aws_iam_role" "policy_evaluator_exec" {
  name = "inbox-janitor-policy-evaluator-exec-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_policy" "dynamodb_stream_read" {
  name        = "inbox-janitor-dynamodb-stream-read"
  description = "Allows Policy Evaluator Lambda to read records from DynamoDB Streams"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:DescribeStream",
        "dynamodb:ListStreams"
      ]
      Resource = aws_dynamodb_table.multitenant_rules.stream_arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "policy_evaluator_logs" {
  role       = aws_iam_role.policy_evaluator_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "policy_evaluator_custom" {
  for_each = {
    dynamodb        = aws_iam_policy.dynamodb_access.arn
    dynamodb_stream = aws_iam_policy.dynamodb_stream_read.arn
    sqs_send        = aws_iam_policy.ingest_sqs_send.arn
  }

  role       = aws_iam_role.policy_evaluator_exec.name
  policy_arn = each.value
}

resource "aws_lambda_function" "policy_evaluator" {
  function_name = "inbox-janitor-policy-evaluator-tf"
  role          = aws_iam_role.policy_evaluator_exec.arn
  handler       = "index.lambda_handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 60
  memory_size   = 128

  filename         = data.archive_file.policy_evaluator_zip.output_path
  source_code_hash = data.archive_file.policy_evaluator_zip.output_base64sha256

  environment {
    variables = {
      MULTITENANT_RULES_TABLE  = aws_dynamodb_table.multitenant_rules.name
      ENFORCE_QUEUE_URL_CANARY = aws_sqs_queue.enforce_canary_queue.url
      ENFORCE_QUEUE_URL_PROD   = aws_sqs_queue.enforce_prod_queue.url
      CANARY_TENANTS           = jsonencode(local.canary_tenants)
      SHADOW_MODE              = "true"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.policy_evaluator_logs,
    aws_iam_role_policy_attachment.policy_evaluator_custom
  ]
}

resource "aws_lambda_event_source_mapping" "ddb_stream_to_policy_evaluator" {
  event_source_arn                   = aws_dynamodb_table.multitenant_rules.stream_arn
  function_name                      = aws_lambda_function.policy_evaluator.arn
  starting_position                  = "LATEST"
  batch_size                         = 25
  maximum_batching_window_in_seconds = 1
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 3

  # Prevent infinite loops: ONLY trigger on LOG# writes (ignore SENDER#, SYSTEM_STATE, CONFIG)
  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT", "MODIFY"]
        dynamodb = {
          Keys = {
            SK = {
              S = [{ prefix = "LOG#" }]
            }
          }
        }
      })
    }
  }
}