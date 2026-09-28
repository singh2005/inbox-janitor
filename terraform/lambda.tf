# 1. Download Linux ARM64 wheels directly into layer structure
resource "null_resource" "build_google_api_layer" {
  triggers = {
    requirements_hash = filemd5("${path.module}/../src/layer/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<EOF
      rm -rf ${path.module}/layer_build && \
      mkdir -p ${path.module}/layer_build/python/lib/python3.12/site-packages && \
      pip install \
        --platform manylinux2014_aarch64 \
        --target=${path.module}/layer_build/python/lib/python3.12/site-packages \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        -r ${path.module}/../src/layer/requirements.txt
    EOF
  }
}

# 2. Archive the built layer directory into a zip
data "archive_file" "google_api_layer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/layer_build"
  output_path = "${path.module}/builds/google_api_layer.zip"

  depends_on = [null_resource.build_google_api_layer]
}

# 3. Create the Lambda Layer resource in AWS
resource "aws_lambda_layer_version" "google_api_layer" {
  filename            = data.archive_file.google_api_layer_zip.output_path
  source_code_hash    = data.archive_file.google_api_layer_zip.output_base64sha256
  layer_name          = "google-api-python-layer-linux-tf"
  compatible_runtimes = ["python3.12"]
  compatible_architectures = ["arm64"]
  description         = "Google API Client libraries for Python 3.12 (ARM64)"
}

# 4. Archive function code
data "archive_file" "ingest_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../src/ingest/index.py"
  output_path = "${path.module}/builds/ingest_lambda.zip"
}

# 5. Provision Ingest Lambda Function
resource "aws_lambda_function" "ingest_engine" {
  function_name    = "inbox-janitor-ingest-tf"
  role             = aws_iam_role.ingest_lambda_exec.arn
  handler          = "index.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 128

  filename         = data.archive_file.ingest_lambda_zip.output_path
  source_code_hash = data.archive_file.ingest_lambda_zip.output_base64sha256

  # Attach your existing layer via the data lookup
  layers = [
    data.aws_lambda_layer_version.google_api_layer.arn
  ]

  # Map environment variables to your provisioned infrastructure
  environment {
    variables = {
      LOGS_TABLE  = aws_dynamodb_table.raw_email_logs.name
      RULES_TABLE = aws_dynamodb_table.active_routing_rules.name
      SECRET_ARN  = local.gmail_credentials_secret_arn
    }
  }

  # Ensure IAM permissions & roles exist BEFORE attempting to create the function
  depends_on = [
    aws_iam_role_policy_attachment.custom_attachments,
    aws_iam_role_policy_attachment.lambda_logs,
    aws_lambda_layer_version.google_api_layer
  ]
}