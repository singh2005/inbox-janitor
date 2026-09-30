# 1. GCP Pub/Sub Topic for Gmail Watch Notifications
resource "google_pubsub_topic" "gmail_push_topic" {
  name = "gmail-inbox-events"
}

# 2. Grant Gmail system service account permission to publish to the topic
resource "google_pubsub_topic_iam_binding" "gmail_push_publisher" {
  topic = google_pubsub_topic.gmail_push_topic.name
  role  = "roles/pubsub.publisher"

  members = [
    "serviceAccount:gmail-api-push@system.gserviceaccount.com",
  ]
}

# 3. Push Subscription delivering webhooks directly to API Gateway V2
resource "google_pubsub_subscription" "gmail_push_subscription" {
  name  = "gmail-inbox-events-push"
  topic = google_pubsub_topic.gmail_push_topic.name

  # Message retention and ack configuration
  ack_deadline_seconds       = 20
  message_retention_duration = "604800s" # 7 days
  retain_acked_messages      = false

  push_config {
    # Dynamically references the API Gateway endpoint from apigateway.tf
    push_endpoint = "${aws_apigatewayv2_api.ingest_api.api_endpoint}/gmail-event"

    attributes = {
      x-goog-version = "v1"
    }
  }

  depends_on = [
    aws_apigatewayv2_route.post_gmail_event_route,
    aws_apigatewayv2_stage.default
  ]
}

# Outputs for reference
output "gcp_pubsub_topic_name" {
  value       = google_pubsub_topic.gmail_push_topic.id
  description = "Full GCP Pub/Sub topic string required for Gmail API users.watch call"
}