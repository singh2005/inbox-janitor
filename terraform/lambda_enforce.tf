data "archive_file" "enforce_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../src/enforce/index.py"
  output_path = "${path.module}/builds/enforce_lambda.zip"
}

# 2. Create IAM Role for Enforce Lambda
resource "aws_iam_role" "enforce_lambda_exec" {
  name = "inbox-janitor-enforce-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "enforce_lambda_logs" {
  role       = aws_iam_role.enforce_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "enforce_custom_attachments" {
  for_each = {
    dynamodb       = aws_iam_policy.dynamodb_access.arn
    ssm_parameters = aws_iam_policy.ssm_parameter_access.arn
  }

  role       = aws_iam_role.enforce_lambda_exec.name
  policy_arn = each.value
}

resource "aws_iam_role_policy_attachment" "enforce_sqs_execution" {
  role       = aws_iam_role.enforce_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
}

resource "aws_lambda_function" "enforce_engine" {
  function_name = "inbox-janitor-enforce-tf"
  role          = aws_iam_role.enforce_lambda_exec.arn
  handler       = "index.lambda_handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 120
  memory_size   = 128

  filename         = data.archive_file.enforce_lambda_zip.output_path
  source_code_hash = data.archive_file.enforce_lambda_zip.output_base64sha256

  publish = true

  layers = [
    aws_lambda_layer_version.google_api_layer.arn
  ]

  environment {
    variables = {
      RULES_TABLE             = aws_dynamodb_table.active_routing_rules.name
      MULTITENANT_RULES_TABLE = aws_dynamodb_table.multitenant_rules.name
      SECRET_ARN              = local.gmail_credentials_secret_arn
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.enforce_custom_attachments,
    aws_iam_role_policy_attachment.enforce_lambda_logs,
    aws_lambda_layer_version.google_api_layer
  ]
}

# --- LAMBDA ALIASES ---

resource "aws_lambda_alias" "enforce_prod" {
  name             = "PROD"
  description      = "Stable production release for general tenants"
  function_name    = aws_lambda_function.enforce_engine.function_name
  function_version = aws_lambda_function.enforce_engine.version
}

resource "aws_lambda_alias" "enforce_canary" {
  name             = "CANARY"
  description      = "Canary release alias for targeted account validation"
  function_name    = aws_lambda_function.enforce_engine.function_name
  function_version = "$LATEST"
}