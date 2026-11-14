resource "aws_cloudwatch_dashboard" "inbox_janitor_pipeline" {
  dashboard_name = "InboxJanitor-Pipeline-Health"

  dashboard_body = jsonencode({
    widgets = [
      # =====================================================================
      # STAGE 1: INGRESS (API Gateway Pub/Sub Webhooks & Ingress SQS FIFO)
      # =====================================================================
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "1A. API Gateway Webhook Ingress (Allowed vs Denied)"
          region  = "us-east-1"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.ingest_api.id, { stat = "Sum", period = 300, label = "Total Requests" }],
            ["AWS/ApiGateway", "4xx", "ApiId", aws_apigatewayv2_api.ingest_api.id, { stat = "Sum", period = 300, color = "#ff7f0e", label = "4xx Denied / Auth Failed" }],
            ["AWS/ApiGateway", "5xx", "ApiId", aws_apigatewayv2_api.ingest_api.id, { stat = "Sum", period = 300, color = "#d62728", label = "5xx Gateway Errors" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "1B. Ingress SQS FIFO & Router Lambda"
          region  = "us-east-1"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.ingress_queue.name, { stat = "Sum", period = 300, label = "Enqueued to Ingress" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.ingress_queue.name, { stat = "Maximum", period = 300, label = "Ingress Backlog" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.ingress_dlq.name, { stat = "Maximum", period = 300, color = "#d62728", label = "Ingress DLQ" }],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.router_engine.function_name, { stat = "Sum", period = 300, label = "Router Invocations" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.router_engine.function_name, { stat = "Sum", period = 300, color = "#d62728", label = "Router Errors" }]
          ]
        }
      },

      # =====================================================================
      # STAGE 2: INGESTION (Ingest Lambda & Gmail Sync Outcomes from Logs)
      # =====================================================================
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "2A. Ingest Lambda Health & Latency"
          region  = "us-east-1"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.ingest_engine.function_name, { stat = "Sum", period = 300, label = "Invocations" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.ingest_engine.function_name, { stat = "Sum", period = 300, color = "#d62728", label = "Errors" }],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.ingest_engine.function_name, { stat = "Average", period = 300, yAxis = "right", label = "Avg Duration (ms)" }]
          ]
          yAxis = {
            left  = { min = 0 }
            right = { min = 0 }
          }
        }
      },
      {
        type   = "log"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "2B. Ingest Log Outcomes (Completed vs Skipped vs Errors)"
          region = "us-east-1"
          view   = "timeSeries"
          query  = <<-EOT
            SOURCE '/aws/lambda/${aws_lambda_function.ingest_engine.function_name}'
            | fields @timestamp, @message
            | filter @message like /Finished Ingest Pass|Skipping message|Error|Failed/
            | stats count(@message like /Finished Ingest Pass/) as CompletedPasses,
                    count(@message like /Skipping message/) as IgnoredNonInboxTrash,
                    count(@message like /Error|Failed/) as LogErrors
              by bin(15m)
          EOT
        }
      },

      # =====================================================================
      # STAGE 3: STREAM & POLICY EVALUATION (DDB Streams -> Policy Evaluator)
      # =====================================================================
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title   = "3A. Policy Evaluator & DDB Stream Lag"
          region  = "us-east-1"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.policy_evaluator.function_name, { stat = "Sum", period = 300, label = "Evaluator Invocations" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.policy_evaluator.function_name, { stat = "Sum", period = 300, color = "#d62728", label = "Evaluator Errors" }],
            ["AWS/Lambda", "IteratorAge", "FunctionName", aws_lambda_function.policy_evaluator.function_name, { stat = "Maximum", period = 300, yAxis = "right", color = "#9467bd", label = "Stream Iterator Age (ms)" }],
            ["AWS/DynamoDB", "SystemErrors", "TableName", aws_dynamodb_table.multitenant_rules.name, { stat = "Sum", period = 300, color = "#d62728", label = "DDB System Errors" }]
          ]
          yAxis = {
            left  = { min = 0 }
            right = { min = 0 }
          }
        }
      },
      {
        type   = "log"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "3B. Policy Decisions & SQS Enqueues (From Logs)"
          region = "us-east-1"
          view   = "timeSeries"
          query  = <<-EOT
            SOURCE '/aws/lambda/${aws_lambda_function.policy_evaluator.function_name}'
            | fields @timestamp, @message
            | filter @message like /Policy: |\[ENQUEUE TRACE\] SQS Accepted/
            | stats count(@message like /Policy: ALLOW/) as PolicyAllow,
                    count(@message like /Policy: DELETE/) as PolicyDelete,
                    count(@message like /\[ENQUEUE TRACE\] SQS Accepted/) as EnqueuedToTrash
              by bin(15m)
          EOT
        }
      },

      # =====================================================================
      # STAGE 4: ENFORCEMENT (Canary & Prod SQS Queues -> Enforce Lambda)
      # =====================================================================
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 12
        height = 6
        properties = {
          title   = "4A. Enforce SQS Queues & DLQs (Canary + Prod)"
          region  = "us-east-1"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.enforce_canary_queue.name, { stat = "Sum", period = 300, label = "Canary Enqueued" }],
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.enforce_prod_queue.name, { stat = "Sum", period = 300, label = "Prod Enqueued" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.enforce_canary_queue.name, { stat = "Maximum", period = 300, label = "Canary Backlog" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.enforce_prod_queue.name, { stat = "Maximum", period = 300, label = "Prod Backlog" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.enforce_canary_dlq.name, { stat = "Maximum", period = 300, color = "#d62728", label = "Canary DLQ" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.enforce_prod_dlq.name, { stat = "Maximum", period = 300, color = "#d62728", label = "Prod DLQ" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 18
        width  = 12
        height = 6
        properties = {
          title   = "4B. Enforce Lambda Executions & Latency"
          region  = "us-east-1"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.enforce_engine.function_name, { stat = "Sum", period = 300, label = "Invocations" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.enforce_engine.function_name, { stat = "Sum", period = 300, color = "#d62728", label = "Errors" }],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.enforce_engine.function_name, { stat = "Average", period = 300, yAxis = "right", label = "Avg Duration (ms)" }]
          ]
          yAxis = {
            left  = { min = 0 }
            right = { min = 0 }
          }
        }
      },

      # =====================================================================
      # STAGE 5: UNIFIED ERROR & EXCEPTION STREAM ACROSS ALL 4 LAMBDAS
      # =====================================================================
      {
        type   = "log"
        x      = 0
        y      = 24
        width  = 24
        height = 6
        properties = {
          title  = "5. Live Pipeline Errors & Exceptions (All 4 Lambdas)"
          region = "us-east-1"
          view   = "table"
          query  = <<-EOT
            SOURCE '/aws/lambda/${aws_lambda_function.router_engine.function_name}'
            | SOURCE '/aws/lambda/${aws_lambda_function.ingest_engine.function_name}'
            | SOURCE '/aws/lambda/${aws_lambda_function.policy_evaluator.function_name}'
            | SOURCE '/aws/lambda/${aws_lambda_function.enforce_engine.function_name}'
            | fields @timestamp, @logStream, @message
            | filter @message like /\[ERROR\]|ERROR|Exception|Traceback|Failed|REJECTED/
            | sort @timestamp desc
            | limit 50
          EOT
        }
      }
    ]
  })
}