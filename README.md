# Inbox Janitor

An event-driven, cloud-native inbox management engine that automatically identifies, logs, and cleans up persistent clutter in your Gmail account—operating in real-time with zero manual rule maintenance.

---

## 📊 Pipeline Impact Statistics

![Emails Trashed](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/YOUR_USERNAME/YOUR_GIST_ID/raw/total_badge.json)

### 🏆 Top Trashed Senders
<!-- TOP_SENDERS_START -->
<!-- TOP_SENDERS_END -->

## What Inbox Janitor Offers

Inbox Janitor turns your Gmail inbox into a self-healing environment. Instead of forcing you to build and update static email filters, it acts as an intelligent supervisor that monitors sender habits, calculates engagement streaks, and enforces automated cleanup policies dynamically.

### Key Capabilities

* **Automated Unread Streak Detection:** Evaluates a rolling window of recent emails per sender (e.g., 6 consecutive messages). If a sender continuously sends unread marketing emails or newsletters, their status escalates automatically.
* **Autonomous Trash Enforcement:** When a sender triggers a persistent unread streak, their incoming messages bypass your main view and route straight to Gmail Trash.
* **Human-in-the-Loop Feedback:** Adjusts to your natural behavior. The moment you read or retrieve an email from Trash, the system instantly recalculates the sender's engagement streak and restores their policy to `ALLOW`.
* **Zero-Polling, Real-Time Architecture:** Reacts instantly as email events occur rather than running on slow scheduled cron intervals.

---

## The Event-Driven Loop: Dynamic Behavior Enforcement

Inbox Janitor operates on an immediate feedback loop between Google Gmail, AWS, and your actual daily email habits.
```text
                          [ User Receives/Reads Email ]
                                        │
                                        ▼
                                 ( Google Gmail )
                                        │
                                        │ Real-Time Push Event
                                        ▼
                              [ GCP Pub/Sub Topic ]
                                        │
                                        │ Webhook Delivery
                                        ▼
                          [ AWS Ingest & State Engine ]
                                        │
                                        ├────────────────────────────────┐
                                        │                                │
                              ( Unread Streak == 6/6 )                 ( Unread Streak < 6/6 )
                                        │                                │
                                        ▼                                ▼
                              Policy: DELETE                     Policy: ALLOW
                              (Auto-trash)                      (Inbox delivery)

```

### How You Control the Rules Just By Using Your Inbox

You never need to log into AWS, edit a database, or update routing rules manually. Your day-to-day interactions with your inbox serve as the single source of truth:

1. **Automatic Escalation (`ALLOW` -> `DELETE`):** A newsletter sends 6 emails in a row that sit unread. The system flags the sender with a `6/6` unread streak and automatically sets their active policy to `DELETE`.
2. **Instant Reversion (`DELETE` -> `ALLOW`):** If a message from that sender is moved to Trash but turns out to be important, simply **open and read the email** in your Trash folder.
3. **Real-Time Policy Reset:** The read status change fires a real-time push event via GCP Pub/Sub directly to the AWS ingest engine. The system recalculates the rolling window (e.g., dropping the streak to `5/6`), instantly updates the sender's active policy back to `ALLOW`, and ensures future emails land safely back in your inbox.

---

## Cloud-Native Infrastructure & One-Click Deployment

While the primary value lies in its event-driven automation, the solution is designed from the ground up to be lightweight, secure, and effortlessly deployable into any cloud environment.

* **Dual-Cloud Architecture (AWS + GCP):** Harnesses Google Cloud Pub/Sub for native Gmail event streaming and AWS Serverless (API Gateway, Lambda, DynamoDB, Secrets Manager) for processing and policy evaluation.
* **100% Infrastructure as Code (Terraform):** Everything—IAM roles, environment variables, DynamoDB tables, Lambda functions, and API bindings—is codified in Terraform.
* **Zero Server Overhead:** Uses fully managed serverless components that scale down to zero when idle, fitting entirely within AWS and GCP Free Tier limits for standard personal use.
* **Turnkey Setup:** Anyone can clone the repository, supply their OAuth credentials, and run `terraform apply` to spin up a fully functioning, personal inbox cleanup engine in minutes.