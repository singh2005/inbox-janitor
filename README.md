# Inbox Janitor

An event-driven, silent inbox management engine that automatically identifies and cleans up persistent clutter in Gmail — operating in real time with zero manual rule maintenance.

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

Inbox Janitor turns Gmail into a self-cleaning, clutter-free environment. Instead of forcing you to write and maintain brittle email filters, it acts as an event-driven supervisor that tracks sender engagement across a rolling window, evaluates policies asynchronously via Change Data Capture (CDC), and enforces cleanup dynamically.

### Key Capabilities

* **Automated Unread Streak Detection:** Evaluates a rolling window of the 6 most recent messages per sender. Once a sender reaches 6 consecutive `UNREAD` messages (`6/6 UNREAD`), their active policy automatically escalates from `ALLOW` to `DELETE`.
* **Strict `INBOX` & `TRASH` Domain Boundary:** Syncs state only for messages residing in `INBOX` or `TRASH` (ignoring Spam, Sent, and custom archive folders) to track arrivals, read/unread state changes, and user rescues accurately.
* **Autonomous Trash Enforcement:** Newly arriving messages (`INSERT` events) from senders with an active `DELETE` policy are dispatched to tenant-routed SQS FIFO queues (`CANARY` / `PROD`) and automatically moved to Gmail Trash.
* **Human-in-the-Loop Safety (Zero Tug-of-War):** Rescuing an email from Trash (`Move to Inbox`) or opening it updates the message state (`MODIFY` event) without re-triggering enforcement. Reading a single message drops the rolling streak below `6/6` and immediately resets the sender's policy back to `ALLOW`.
* **Zero-Polling, Real-Time Architecture:** Reacts within seconds to mailbox changes via Gmail `users.watch()` and Google Cloud Pub/Sub OIDC-authenticated push webhooks.

---

## Event-Driven CDC Architecture

Inbox Janitor decouples **ingestion**, **policy evaluation**, and **enforcement** using DynamoDB Streams and SQS FIFO queues so each stage scales, retries, and fails independently under strict least-privilege IAM boundaries:

```text
                        [ User Receives / Reads / Rescues Email ]
                                            │
                                            ▼
                                    ( Google Gmail )
                                            │  Real-Time Watch Notification
                                            ▼
                              [ GCP Pub/Sub Push Subscription ]
                               (Signed Google OIDC Bearer JWT)
                                            │  POST /gmail-event
                                            ▼
                                [ AWS API Gateway V2 (HTTP) ]
                               (OIDC JWT Authorizer + Throttling)
                                            │
                                            ▼
                                  [ Ingress SQS FIFO Queue ]
                               (Content-Based Deduplication + DLQ)
                                            │
                                            ▼
                                  [ Router Lambda Engine ]
                            (Multi-Tenant Canary / Prod Routing)
                                            │
                             ┌──────────────┴──────────────┐
                             ▼                             ▼
                   [ Ingest: :CANARY ]           [ Ingest: :PROD ]
                      (Gmail History API Sync — gmail.metadata)
                                            │
                                            ▼
                        [ DynamoDB: inbox-janitor-multitenant-rules ]
                         (Single-Table Design + 45-Day TTL + Streams)
                                            │
                                            │  CDC Stream (SK prefix: LOG#)
                                            ▼
                              [ Policy Evaluator Lambda ]
                         (Rolling 6-Msg Window & State Machine)
                             │                             │
                  (INSERT + DELETE)             (MODIFY / ALLOW)
                             │                             │
                             ▼                             ▼
             [ Canary Enforce SQS FIFO ]        [ State Updated Only ]
             [  Prod Enforce SQS FIFO  ]        (No Enforcement Loop)
                             │
                             ▼
               [ Enforce Lambda (:CANARY / :PROD) ]
                  (Gmail API Trash — gmail.modify)
```

## How You Control Rules Just By Using Your Inbox

No web console, database edits, or manual filter rules are required — normal inbox behavior drives the state machine:
* **Automatic Escalation (ALLOW → DELETE):** A newsletter sends 6 emails in a row that sit unread. The system flags the sender with a 6/6 unread streak and automatically sets their active policy to DELETE.
* **Instant Reversion (DELETE → ALLOW):** If a message from that sender is moved to Trash but turns out to be important, simply open and read the email in your Trash folder.
* **Real-Time Policy Reset:** The read status change fires a real-time push event via GCP Pub/Sub directly to the AWS ingest engine. The system recalculates the rolling window (e.g., dropping the streak to 5/6), instantly updates the sender's active policy back to ALLOW, and ensures future emails land safely in your primary inbox.
---
## Cloud-Native Infrastructure & One-Click Deployment
Designed from the ground up to be lightweight, secure, resilient, and effortlessly deployable into AWS cloud environment.
* **Cross-Cloud Zero-Trust Ingress:** GCP Pub/Sub authenticates webhook deliveries using short-lived Google OIDC JWTs validated natively by an AWS API Gateway V2 JWT Authorizer (`accounts.google.com` issuer + exact audience binding) before messages enter SQS.
* **Change Data Capture (CDC) & Loop Prevention:** DynamoDB Streams filter strictly on SK prefix LOG#, isolating policy evaluation from SENDER#, SYSTEM_STATE, and METRICS writes and eliminating recursive stream loops.
* **Fault Tolerance & Observability:** Every asynchronous boundary uses SQS FIFO queues with ReportBatchItemFailures and Dead-Letter Queues (DLQs), paired with a unified CloudWatch dashboard tracking end-to-end funnel throughput, stream IteratorAge, and Logs Insights error streams.
* **100% Infrastructure as Code (Terraform):** All AWS and GCP resources—API Gateway, JWT Authorizer, Pub/Sub topic/subscription, IAM policies, DynamoDB tables/streams, SQS FIFO queues, Lambda aliases, and CloudWatch dashboards—are provisioned declaratively via Terraform.
* **Multi-Tenant SaaS & Self-Service Onboarding:** Prefer a zero-setup managed experience over self-hosting? Users can self-onboard directly at [inbox-janitor.com](https://inbox-janitor.com) via a multi-tenant control plane featuring automated Google OAuth provisioning and subscription lifecycle management.
---
## Privacy & Gmail Permissions Audit

Inbox Janitor is built on a zero-body-access model. During OAuth setup, the application requests only two narrow Gmail scopes, and you can verify the exact lines of code where they are used:

* **Header-Only Ingestion (`gmail.metadata`):** Used in [`src/ingest/gmail_client.py#L30`](https://github.com/singh2005/inbox-janitor/blob/main/src/ingest/gmail_client.py#L30) to read message headers (such as `From`, `Subject`, and `List-Unsubscribe`) and set up Gmail Pub/Sub push notifications. Inbox Janitor never requests `gmail.readonly` and cannot read, parse, or store email bodies or attachments.
* **Trash Enforcement (`gmail.modify`):** Used in [`src/enforce/index.py#L33`](https://github.com/singh2005/inbox-janitor/blob/main/src/enforce/index.py#L33) strictly to move matched clutter messages to Trash (`addLabelIds: ["TRASH"]`).

### Why Google Shows an "Unverified App" Warning During Early Access
Because `gmail.metadata` and `gmail.modify` are classified by Google as restricted scopes, Google displays a standard *"Google hasn't verified this app"* screen until formal OAuth verification and security assessment are completed. During early access, click **Advanced → Go to inbox-janitor.com (unsafe)** and check **Select all** to authorize both scopes.
