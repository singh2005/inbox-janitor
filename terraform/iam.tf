resource "aws_iam_role" "ingest_lambda_exec" {
  name = "inbox-janitor-ingest-lambda-exec-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_policy" "dynamodb_access" {
  name        = "inbox-janitor-dynamodb-access"
  description = "Allows read/write access to Inbox Janitor DynamoDB tables"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:BatchGetItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:UpdateItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:DeleteItem"
      ]
      Resource = [
        aws_dynamodb_table.multitenant_rules.arn,
        "${aws_dynamodb_table.multitenant_rules.arn}/*"
      ]
    }]
  })
}

resource "aws_iam_policy" "secrets_manager_access" {
  name        = "inbox-janitor-secrets-manager-access"
  description = "Allows reading Google OAuth secrets from Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = local.gmail_credentials_secret_arn
    }]
  })
}

resource "aws_iam_policy" "allow_invoke_enforce_lambda" {
  name        = "inbox-janitor-allow-invoke-enforce-lambda"
  description = "Allows ingest engine to invoke enforce execution lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = "arn:aws:lambda:us-east-1:*:function:inbox-janitor-enforce*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.ingest_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "custom_attachments" {
  for_each = {
    dynamodb        = aws_iam_policy.dynamodb_access.arn
    secrets_manager = aws_iam_policy.secrets_manager_access.arn
    invoke_enforce  = aws_iam_policy.allow_invoke_enforce_lambda.arn
  }

  role       = aws_iam_role.ingest_lambda_exec.name
  policy_arn = each.value
}

resource "aws_iam_policy" "ingest_sqs_send" {
  name        = "inbox-janitor-ingest-sqs-send"
  description = "Allows ingest lambda to push message records to enforce FIFO queue"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["sqs:SendMessage"]
        Effect   = "Allow"
        Resource = aws_sqs_queue.enforce_queue.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ingest_sqs_attach" {
  role       = aws_iam_role.ingest_lambda_exec.name
  policy_arn = aws_iam_policy.ingest_sqs_send.arn
}
