resource "aws_cloudwatch_log_group" "ingest_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.ingest_engine.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "enforce_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.enforce_engine.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "router_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.router_engine.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "policy_evaluator_logs" {
  name              = "/aws/lambda/${aws_lambda_function.policy_evaluator.function_name}"
  retention_in_days = 14
}