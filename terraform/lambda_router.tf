data "archive_file" "router_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../src/router/index.py"
  output_path = "${path.module}/builds/router_lambda.zip"
}

resource "aws_lambda_function" "router_engine" {
  function_name = "inbox-janitor-router-tf"
  role          = aws_iam_role.router_lambda_exec.arn
  handler       = "index.lambda_handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 10
  memory_size   = 128

  filename         = data.archive_file.router_lambda_zip.output_path
  source_code_hash = data.archive_file.router_lambda_zip.output_base64sha256

  environment {
    variables = {
      INGEST_FUNCTION_NAME    = aws_lambda_function.ingest_engine.function_name
      MULTITENANT_RULES_TABLE = aws_dynamodb_table.multitenant_rules.name
    }
  }
}

resource "aws_iam_role" "router_lambda_exec" {
  name = "inbox-janitor-router-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "router_logs" {
  role       = aws_iam_role.router_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "router_sqs_execution" {
  role       = aws_iam_role.router_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
}

resource "aws_iam_policy" "router_invoke_ingest" {
  name = "inbox-janitor-router-invoke-ingest"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "${aws_lambda_function.ingest_engine.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:Query"]
        Resource = aws_dynamodb_table.multitenant_rules.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "router_invoke_attach" {
  role       = aws_iam_role.router_lambda_exec.name
  policy_arn = aws_iam_policy.router_invoke_ingest.arn
}