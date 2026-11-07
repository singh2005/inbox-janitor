# Fetch current GCP project details to target the Pub/Sub System Service Agent
data "google_project" "current" {}

# 1. Dedicated Service Account that GCP Pub/Sub will impersonate to issue OIDC JWTs
resource "google_service_account" "pubsub_invoker" {
  account_id   = "gmail-pubsub-invoker-sa"
  display_name = "PubSub Push Service Account for API Gateway Webhook"
}

# 2. Grant GCP's internal Pub/Sub Service Agent rights to mint tokens for the above SA
resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = google_service_account.pubsub_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# 3. GCP Pub/Sub Topic for Gmail Watch Notifications
resource "google_pubsub_topic" "gmail_push_topic" {
  name = "gmail-inbox-events"
}

# 4. Grant Gmail System Account permission to publish incoming email events
resource "google_pubsub_topic_iam_binding" "gmail_push_publisher" {
  topic = google_pubsub_topic.gmail_push_topic.name
  role  = "roles/pubsub.publisher"

  members = [
    "serviceAccount:gmail-api-push@system.gserviceaccount.com",
  ]
}

# 5. Push Subscription delivering OIDC-authenticated webhooks to API Gateway
resource "google_pubsub_subscription" "gmail_push_subscription" {
  name  = "gmail-inbox-events-push"
  topic = google_pubsub_topic.gmail_push_topic.name

  ack_deadline_seconds       = 20
  message_retention_duration = "604800s" # 7 days
  retain_acked_messages      = false

  push_config {
    push_endpoint = "${aws_apigatewayv2_api.ingest_api.api_endpoint}/gmail-event"

    attributes = {
      x-goog-version = "v1"
    }

    # Automatically attaches 'Authorization: Bearer <JWT>' to requests
    oidc_token {
      service_account_email = google_service_account.pubsub_invoker.email
      
      # Match the exact API Gateway endpoint URL (serves as the JWT 'aud' claim)
      audience = "${aws_apigatewayv2_api.ingest_api.api_endpoint}/gmail-event"
    }
  }

  depends_on = [
    aws_apigatewayv2_route.post_gmail_event_route,
    aws_apigatewayv2_stage.default,
    google_service_account_iam_member.pubsub_token_creator
  ]
}

# GCP Outputs
output "gcp_pubsub_topic_name" {
  value       = google_pubsub_topic.gmail_push_topic.id
  description = "Full GCP Pub/Sub topic string for Gmail API users.watch call"
}

output "gcp_pubsub_invoker_email" {
  value       = google_service_account.pubsub_invoker.email
  description = "Service Account email issuing the OIDC token"
}
