data "archive_file" "google_api_layer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/layer_build"
  output_path = "${path.module}/builds/google_api_layer.zip"
}

resource "aws_lambda_layer_version" "google_api_layer" {
  filename = data.archive_file.google_api_layer_zip.output_path
  # Hash requirements.txt directly instead of the generated zip output
  source_code_hash         = filebase64sha256("${path.module}/../src/layer/requirements.txt")
  layer_name               = "google-api-python-layer-linux-tf"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
  description              = "Google API Client libraries for Python 3.12 (ARM64)"
}

data "archive_file" "ingest_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../src/ingest/index.py"
  output_path = "${path.module}/builds/ingest_lambda.zip"
}

resource "aws_lambda_function" "ingest_engine" {
  function_name = "inbox-janitor-ingest-tf"
  role          = aws_iam_role.ingest_lambda_exec.arn
  handler       = "index.lambda_handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 60
  memory_size   = 128

  filename         = data.archive_file.ingest_lambda_zip.output_path
  source_code_hash = data.archive_file.ingest_lambda_zip.output_base64sha256

  # Attach your existing layer via the data lookup
  layers = [
    aws_lambda_layer_version.google_api_layer.arn
  ]

  # Map environment variables to your provisioned infrastructure
  environment {
    variables = {
      LOGS_TABLE        = aws_dynamodb_table.raw_email_logs.name
      RULES_TABLE       = aws_dynamodb_table.active_routing_rules.name
      SECRET_ARN        = local.gmail_credentials_secret_arn
      GCP_PUBSUB_TOPIC  = google_pubsub_topic.gmail_push_topic.id
      ENFORCE_QUEUE_URL = aws_sqs_queue.enforce_queue.url
    }
  }

  # Ensure IAM permissions & roles exist BEFORE attempting to create the function
  depends_on = [
    aws_iam_role_policy_attachment.custom_attachments,
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.ingest_sqs_attach,
    aws_lambda_layer_version.google_api_layer
  ]
}