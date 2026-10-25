resource "aws_cloudwatch_dashboard" "inbox_janitor_pipeline" {
  dashboard_name = "InboxJanitor-Pipeline-Health"

  dashboard_body = jsonencode({
    widgets = [
      # Widget 1: API Gateway & Ingest Lambda Overview
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.ingest_api.id, { stat = "Sum", period = 60 }],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.ingest_engine.function_name, { stat = "Sum", period = 60 }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.ingest_engine.function_name, { stat = "Sum", period = 60, color = "#d62728" }],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.ingest_engine.function_name, { stat = "Average", period = 60, yAxis = "right" }]
          ]
          view    = "timeSeries"
          stacked = false
          title   = "Ingress & Ingest Lambda Health"
          region  = "us-east-1"
        }
      },

      # Widget 2: SQS FIFO Depth & DLQ Monitor
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.enforce_queue.name, { stat = "Sum", period = 60 }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.enforce_queue.name, { stat = "Average", period = 60 }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.enforce_dlq.name, { stat = "Maximum", period = 60, color = "#d62728" }]
          ]
          view    = "timeSeries"
          stacked = false
          title   = "SQS Queue Backlog & DLQ Poison Messages"
          region  = "us-east-1"
        }
      },

      # Widget 3: Enforce Lambda Executions & Duration
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.enforce_engine.function_name, { stat = "Sum", period = 60, yAxis = "left" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.enforce_engine.function_name, { stat = "Sum", period = 60, color = "#d62728", yAxis = "left" }],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.enforce_engine.function_name, { stat = "Average", period = 60, yAxis = "right" }]
          ]
          view    = "timeSeries"
          stacked = false
          title   = "Enforce Engine Executions & Latency"
          region  = "us-east-1"
          yAxis = {
            left  = { min = 0 }
            right = { min = 0 }
          }
        }
      },

      # Widget 4: DynamoDB Table Operation Errors & Throttles
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/DynamoDB", "SystemErrors", "TableName", aws_dynamodb_table.raw_email_logs.name, { stat = "Sum", period = 60 }],
            ["AWS/DynamoDB", "SystemErrors", "TableName", aws_dynamodb_table.active_routing_rules.name, { stat = "Sum", period = 60 }]
          ]
          view    = "timeSeries"
          stacked = false
          title   = "DynamoDB System Errors"
          region  = "us-east-1"
        }
      }
    ]
  })
}