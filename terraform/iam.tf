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
        "dynamodb:Query",
        "dynamodb:UpdateItem",
        "dynamodb:BatchWriteItem"
      ]
      Resource = [
        aws_dynamodb_table.raw_email_logs.arn,
        aws_dynamodb_table.active_routing_rules.arn
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
      Resource = data.aws_secretsmanager_secret.gmail_credentials.arn
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