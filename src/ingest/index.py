import base64
from datetime import datetime, timezone
import json
import logging
import os
import time
import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")
sqs_client = boto3.client("sqs")

LOGS_TABLE_NAME = os.environ.get("LOGS_TABLE", "inbox-janitor-raw-email-logs-tf")
RULES_TABLE_NAME = os.environ.get(
    "RULES_TABLE", "inbox-janitor-active-routing-rules-tf"
)
SECRET_ARN = os.environ.get("SECRET_ARN")
GCP_PUBSUB_TOPIC = os.environ.get("GCP_PUBSUB_TOPIC")
ENFORCE_QUEUE_URL = os.environ.get("ENFORCE_QUEUE_URL")

LOGS_TABLE = dynamodb.Table(LOGS_TABLE_NAME)
RULES_TABLE = dynamodb.Table(RULES_TABLE_NAME)

# 45-day retention in seconds (45 * 24 * 60 * 60)
TTL_RETENTION_SECONDS = 3888000


def check_and_renew_gmail_watch(service):
    """
    Renews the Gmail watch subscription only if it's missing or expiring within 24 hours.
    Avoids redundant API calls on every incoming webhook execution pass.
    """
    if not GCP_PUBSUB_TOPIC:
        logger.error("GCP_PUBSUB_TOPIC environment variable is not set!")
        return

    now_ms = int(time.time() * 1000)
    renew_buffer_ms = 24 * 60 * 60 * 1000  # 24 hours in milliseconds

    try:
        # Check current watch expiration stored in DynamoDB
        resp = RULES_TABLE.get_item(Key={"sender_address": "__SYSTEM_STATE__"})
        raw_exp = resp["Item"].get("watch_expiration_ms") if "Item" in resp else None
        current_expiration = int(raw_exp) if raw_exp is not None else None

        # If expiration exists and is more than 24 hours in the future, skip renewal
        if current_expiration and (current_expiration - now_ms > renew_buffer_ms):
            logger.info(
                f"Gmail Watch active. Expiration in "
                f"{(int(current_expiration) - now_ms) // (1000 * 3600)}h. Skipping renew."
            )
            return

        # Register watch call when expired, missing, or close to expiration
        request_body = {"topicName": GCP_PUBSUB_TOPIC}
        response = service.users().watch(userId="me", body=request_body).execute()
        new_expiration_ms = int(response.get("expiration", 0))

        logger.info(f"Gmail Watch Renewed! New Expiration MS: {new_expiration_ms}")

        # Update watch expiration in __SYSTEM_STATE__
        RULES_TABLE.update_item(
            Key={"sender_address": "__SYSTEM_STATE__"},
            UpdateExpression="SET watch_expiration_ms = :exp, updated_at = :ua",
            ExpressionAttributeValues={
                ":exp": new_expiration_ms,
                ":ua": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as e:
        logger.error(f"Failed during check_and_renew_gmail_watch: {str(e)}")


def get_google_credentials():
    response = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret_json = json.loads(response["SecretString"])
    scopes = ["https://www.googleapis.com/auth/gmail.metadata"]
    return Credentials(
        token=None,
        refresh_token=secret_json["refresh_token"],
        client_id=secret_json["client_id"],
        client_secret=secret_json["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=scopes,
    )


def get_last_history_id():
    try:
        resp = RULES_TABLE.get_item(Key={"sender_address": "__SYSTEM_STATE__"})
        if "Item" in resp:
            val = resp["Item"].get("last_history_id")
            return str(val) if val is not None else None
    except Exception as e:
        logger.warning(f"Could not read last_history_id cursor: {str(e)}")
    return None


def save_last_history_id(incoming_history_id):
    try:
        numeric_id = int(incoming_history_id)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        RULES_TABLE.update_item(
            Key={"sender_address": "__SYSTEM_STATE__"},
            UpdateExpression="SET last_history_id = :new_id, updated_at = :ua",
            ConditionExpression="attribute_not_exists(last_history_id) OR last_history_id < :new_id",
            ExpressionAttributeValues={
                ":new_id": numeric_id,
                ":ua": now_iso,
            },
        )
        logger.info(f"Successfully updated __SYSTEM_STATE__ cursor to {numeric_id}")
    except boto3.client("dynamodb").exceptions.ConditionalCheckFailedException:
        logger.info(
            f"Skipped updating last_history_id to {incoming_history_id} (superseded"
            " by newer execution pass)."
        )
    except Exception as e:
        logger.error(f"Failed saving last_history_id: {str(e)}")


def enqueue_enforce_records(message_pairs):
    if not message_pairs or not ENFORCE_QUEUE_URL:
        return

    entries = []
    for idx, pair in enumerate(message_pairs):
        entries.append(
            {
                "Id": str(idx),
                "MessageBody": json.dumps(pair),
                "MessageDeduplicationId": pair["message_id"],
                "MessageGroupId": "gmail_enforce_group",
            }
        )

    for i in range(0, len(entries), 10):
        batch_chunk = entries[i : i + 10]
        try:
            response = sqs_client.send_message_batch(
                QueueUrl=ENFORCE_QUEUE_URL, Entries=batch_chunk
            )
            logger.info(
                f"Enqueued {len(batch_chunk)} record(s) to SQS. Failed count:"
                f" {len(response.get('Failed', []))}"
            )
        except Exception as e:
            logger.error(f"Failed pushing batch chunk to SQS: {str(e)}")


def lambda_handler(event, context):
    logger.info("=== Starting Inbox Janitor Ingest Execution Pass ===")

    pubsub_history_id = None
    if "body" in event:
        try:
            body = json.loads(event["body"])
            if "message" in body and "data" in body["message"]:
                decoded_data = base64.b64decode(body["message"]["data"]).decode("utf-8")
                pubsub_event = json.loads(decoded_data)
                pubsub_history_id = pubsub_event.get("historyId")
                logger.info(
                    f"Received Pub/Sub Push for account:"
                    f" {pubsub_event.get('emailAddress')} | History ID:"
                    f" {pubsub_history_id}"
                )
        except Exception as e:
            logger.warning(f"Could not parse body as Pub/Sub payload: {str(e)}")

    creds = get_google_credentials()
    service = build("gmail", "v1", credentials=creds)
    check_and_renew_gmail_watch(service)

    if not pubsub_history_id:
        logger.info("No historyId present in payload. Skipping sync pass.")
        return {
            "statusCode": 200,
            "body": json.dumps("No historyId found; pass skipped."),
        }

    processed_senders = set()
    new_message_pairs = []

    last_history_id = get_last_history_id()

    if not last_history_id:
        logger.info(
            "No previous cursor found in DynamoDB. Initializing __SYSTEM_STATE__"
            f" to {pubsub_history_id}"
        )
        save_last_history_id(pubsub_history_id)
        return {"statusCode": 200, "body": json.dumps("Initialized system cursor.")}

    logger.info(
        "Fetching history records starting from cursor History ID:"
        f" {last_history_id}"
    )

    try:
        history_response = (
            service.users()
            .history()
            .list(userId="me", startHistoryId=str(last_history_id))
            .execute()
        )

        history_records = history_response.get("history", [])
        logger.info(f"Retrieved {len(history_records)} history record(s).")

        for record in history_records:
            if "messagesAdded" in record:
                for item in record["messagesAdded"]:
                    msg_id = item["message"]["id"]
                    sender = process_single_message(service, msg_id)
                    if sender:
                        processed_senders.add(sender)
                        new_message_pairs.append(
                            {"message_id": msg_id, "sender_address": sender}
                        )

            for label_event in record.get("labelsRemoved", []) + record.get(
                "labelsAdded", []
            ):
                msg_id = label_event["message"]["id"]
                sender = process_single_message(service, msg_id)
                if sender:
                    processed_senders.add(sender)

        save_last_history_id(pubsub_history_id)

    except Exception as e:
        logger.error(f"Error querying Gmail History API: {str(e)}")

    if processed_senders:
        evaluate_and_update_policies(processed_senders)

    if new_message_pairs:
        enqueue_enforce_records(new_message_pairs)

    logger.info("=== Finished Inbox Janitor Ingest Execution Pass ===")
    return {"statusCode": 200, "body": json.dumps("Success")}


def process_single_message(service, msg_id):
    try:
        detail = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata")
            .execute()
        )
        headers = {
            h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])
        }

        sender_full = headers.get("From", "Unknown <unknown@example.com>")
        subject = headers.get("Subject", "(No Subject)")
        sender_address = sender_full.split("<")[-1].replace(">", "").lower().strip()
        sender_name = (
            sender_full.split("<")[0].strip() if "<" in sender_full else sender_full
        )

        label_ids = detail.get("labelIds", [])
        status = "UNREAD" if "UNREAD" in label_ids else "READ"

        internal_date_ms = int(detail.get("internalDate", 0))
        iso_timestamp = (
            datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        sort_key = f"{iso_timestamp}#{msg_id}"

        now_epoch = int(time.time())
        ttl_timestamp = now_epoch + TTL_RETENTION_SECONDS

        LOGS_TABLE.put_item(
            Item={
                "sender_address": sender_address,
                "timestamp_message_id": sort_key,
                "message_id": msg_id,
                "sender_name": sender_name,
                "subject": subject,
                "status": status,
                "timestamp": iso_timestamp,
                "ttl_timestamp": ttl_timestamp,
            }
        )
        logger.info(f"Upserted DynamoDB record for {sender_address} | Status: {status}")
        return sender_address
    except Exception as e:
        logger.error(f"Failed processing message {msg_id}: {str(e)}")
        return None


def evaluate_and_update_policies(processed_senders):
    for address in processed_senders:
        query_resp = LOGS_TABLE.query(
            KeyConditionExpression="sender_address = :sa",
            ExpressionAttributeValues={":sa": address},
            ScanIndexForward=False,
            Limit=6,
        )

        items = query_resp.get("Items", [])
        total_sampled = len(items)
        unread_count = sum(1 for item in items if item.get("status") == "UNREAD")

        policy = "DELETE" if (total_sampled == 6 and unread_count == 6) else "ALLOW"
        sender_name = items[0].get("sender_name", "Unknown") if items else "Unknown"
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        RULES_TABLE.update_item(
            Key={"sender_address": address},
            UpdateExpression=(
                "SET sender_name = :sn, unread_streak = :us, active_policy = :ap,"
                " last_evaluated = :le, entity_type = :et, trashed_count ="
                " if_not_exists(trashed_count, :zero)"
            ),
            ExpressionAttributeValues={
                ":sn": sender_name,
                ":us": f"{unread_count}/{total_sampled}",
                ":ap": policy,
                ":le": now_iso,
                ":et": "RULE",
                ":zero": 0,
            },
        )
        logger.info(
            f"Sender: {address} | Window: {unread_count}/{total_sampled} UNREAD |"
            f" Policy: {policy} | GSI set entity_type=RULE"
        )
