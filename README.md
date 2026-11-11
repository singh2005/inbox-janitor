# Inbox Janitor

An event-driven, cloud-native inbox management engine that automatically identifies, logs, and cleans up persistent clutter in your Gmail inbox — operating in real-time with zero manual rule maintenance.

---

## 📊 Pipeline Impact Statistics

<p align="left">
  <img src="https://img.shields.io/badge/dynamic/json?url=https://gist.githubusercontent.com/singh2005/f96228287f159d6c7a91d889c645d9bf/raw/stats.json&query=$.clutter_index&label=Mental%20Clutter%20Index&color=blue" alt="Mental Clutter Index" />
  <img src="https://img.shields.io/badge/dynamic/json?url=https://gist.githubusercontent.com/singh2005/f96228287f159d6c7a91d889c645d9bf/raw/stats.json&query=$.total_trashed&label=Emails%20Trashed&color=blue" alt="Emails Trashed" />
  <img src="https://img.shields.io/badge/dynamic/json?url=https://gist.githubusercontent.com/singh2005/f96228287f159d6c7a91d889c645d9bf/raw/stats.json&query=$.space_recovered&label=Space%20Recovered&color=success" alt="Space Recovered" />
  <img src="https://img.shields.io/badge/dynamic/json?url=https://gist.githubusercontent.com/singh2005/f96228287f159d6c7a91d889c645d9bf/raw/stats.json&query=$.last_updated&label=Last%20Updated&color=informational" alt="Last Updated" />
</p>

---

## What Inbox Janitor Offers

Inbox Janitor turns your Gmail inbox into a self-cleaning clutter-free environment. Instead of forcing you to build and update static email filters, it acts as an intelligent supervisor that monitors sender habits, calculates engagement streaks, and enforces automated cleanup policies dynamically.

### Key Capabilities

* **Automated Unread Streak Detection:** Evaluates a rolling window of recent emails per sender (e.g., 6 consecutive messages). If a sender continuously sends marketing emails or newsletters that you never read, their status escalates automatically.
* **Strict INBOX Scope Filtering:** Processes only incoming messages landing in your primary `INBOX`, ignoring promotional tab updates, sent messages, and archived noise.
* **Autonomous Trash Enforcement:** When a sender triggers a persistent unread streak, their incoming messages bypass your main view and route straight to Gmail Trash via targeted SQS FIFO enforcement workers.
* **Human-in-the-Loop Safety:** Adjusts naturally to your behavior. Gmail automatically retains trashed messages for 30 days. The moment you open or retrieve an email from Trash, the system recalculates the sender's engagement streak and restores their policy to `ALLOW`.
* **Zero-Polling, Real-Time Architecture:** Reacts instantly as email events occur via GCP Pub/Sub push notifications rather than relying on slow, scheduled cron polling.
---

## The Event-Driven Architecture

Inbox Janitor operates on an immediate, decoupled feedback loop between Google Gmail, GCP Pub/Sub, AWS Serverless infrastructure, and your daily email habits.

```text
                                  [ User Receives / Reads Email ]
                                                 │
                                                 ▼
                                          ( Google Gmail )
                                                 │
                                                 │ Real-Time Push Event
                                                 ▼
                                     [ GCP Pub/Sub Subscription ]
                                     (Signed Google OIDC Bearer Token)
                                                 │
                                                 │ Authenticated POST /gmail-event
                                                 ▼
                                  [ AWS API Gateway V2 (HTTP) ]
                                  (JWT Authorizer + Rate Limits)
                                                 │
                                                 ▼
                                   [ Ingress SQS FIFO Queue ]
                                 (Partial Batch Item Failures)
                                                 │
                                                 ▼
                                       [ Router Lambda Engine ]
                                  (Multi-Tenant Routing Cache)
                                                 │
                                 ┌───────────────┴───────────────┐
                                 ▼                               ▼
                      [ Ingest Lambda: CANARY ]       [ Ingest Lambda: PROD ]
                      (label:INBOX Filtering)         (label:INBOX Filtering)
                                 │                               │
                      ┌──────────┴──────────┐         ┌──────────┴──────────┐
                      ▼                     ▼         ▼                     ▼
                [ DynamoDB ]          [ SQS FIFO ]  [ DynamoDB ]          [ SQS FIFO ]
            (LOG# & SENDER Policy)  (Canary Enforce)(LOG# & SENDER Policy)  (Prod Enforce)
                                            │                               │
                                            ▼                               ▼
                                   [ Enforce Lambda ]              [ Enforce Lambda ]
                                   (Gmail API Trash)               (Gmail API Trash)
```

## How You Control Rules Just By Using Your Inbox

You never need to log into AWS, edit a database, or manage routing rules manually. Your day-to-day interactions with your inbox serve as the single source of truth:
* **Automatic Escalation (ALLOW → DELETE):** A newsletter sends 6 emails in a row that sit unread. The system flags the sender with a 6/6 unread streak and automatically sets their active policy to DELETE.
* **Instant Reversion (DELETE → ALLOW):** If a message from that sender is moved to Trash but turns out to be important, simply open and read the email in your Trash folder.
* **Real-Time Policy Reset:** The read status change fires a real-time push event via GCP Pub/Sub directly to the AWS ingest engine. The system recalculates the rolling window (e.g., dropping the streak to 5/6), instantly updates the sender's active policy back to ALLOW, and ensures future emails land safely in your primary inbox.
---
## Cloud-Native Infrastructure & One-Click Deployment
* Designed from the ground up to be lightweight, secure, resilient, and effortlessly deployable into AWS cloud environment.
* **Dual-Cloud Architecture (AWS + GCP):** Harnesses Google Cloud Pub/Sub for native Gmail event streaming and AWS Serverless (API Gateway, SQS FIFO, Lambda, DynamoDB, Secrets Manager) for asynchronous processing, retry handling, and policy evaluation.
* **Canary Release Strategy** Built-in tenant routing allows safe validation of upcoming ingest features via a targeted :CANARY Lambda alias while general traffic remains on :PROD.
* **Fault-Tolerant Queueing:** Decouples ingestion from enforcement using SQS FIFO queues with partial batch failure reporting (ReportBatchItemFailures) and Dead-Letter Queues (DLQ) to ensure zero message loss during transient API errors or rate-limit blips.
* **100% Infrastructure as Code (Terraform):** Everything—IAM roles, environment variables, DynamoDB tables, SQS queues, Lambda functions, and API bindings—is codified in Terraform.
* **Zero Server Overhead:** Uses fully managed serverless components that scale down to zero when idle, fitting entirely within AWS and GCP Free Tier limits for standard personal use.
* **Turnkey Setup:** Anyone can clone the repository, supply their OAuth credentials, and run terraform apply to spin up a fully functioning, personal inbox cleanup engine in minutes.
