resource "aws_cloudwatch_log_group" "ingest_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.ingest_engine.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "enforce_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.enforce_engine.function_name}"
  retention_in_days = 30
}