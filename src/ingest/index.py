import json
import logging
import base64
import os
import boto3
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")

LOGS_TABLE_NAME = os.environ.get("LOGS_TABLE", "inbox-janitor-raw-email-logs-tf")
RULES_TABLE_NAME = os.environ.get(
    "RULES_TABLE", "inbox-janitor-active-routing-rules-tf"
)
SECRET_ARN = os.environ.get("SECRET_ARN")

GCP_PUBSUB_TOPIC = os.environ.get("GCP_PUBSUB_TOPIC")
ENFORCE_LAMBDA_NAME = os.environ.get("ENFORCE_LAMBDA_NAME", "inbox-janitor-enforce-tf")

LOGS_TABLE = dynamodb.Table(LOGS_TABLE_NAME)
RULES_TABLE = dynamodb.Table(RULES_TABLE_NAME)


def register_gmail_watch(service):
    if not GCP_PUBSUB_TOPIC:
        logger.error("GCP_PUBSUB_TOPIC environment variable is not set!")
        return
    request_body = {"topicName": GCP_PUBSUB_TOPIC}
    response = service.users().watch(userId="me", body=request_body).execute()
    logger.info(f"Gmail Watch Registered! Expiration MS: {response.get('expiration')}")


def get_google_credentials():
    response = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret_json = json.loads(response["SecretString"])
    scopes = ["https://www.googleapis.com/auth/gmail.modify"]
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
        RULES_TABLE.put_item(
            Item={
                "sender_address": "__SYSTEM_STATE__",
                "last_history_id": numeric_id,
                "updated_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            },
            ConditionExpression="attribute_not_exists(last_history_id) OR last_history_id < :new_id",
            ExpressionAttributeValues={":new_id": numeric_id},
        )
        logger.info(f"Successfully updated __SYSTEM_STATE__ cursor to {numeric_id}")
    except boto3.client("dynamodb").exceptions.ConditionalCheckFailedException:
        logger.info(
            f"Skipped updating last_history_id to {incoming_history_id} (superseded by newer execution pass)."
        )
    except Exception as e:
        logger.error(f"Failed saving last_history_id: {str(e)}")


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
                    f"Received Pub/Sub Push for account: {pubsub_event.get('emailAddress')} | History ID: {pubsub_history_id}"
                )
        except Exception as e:
            logger.warning(f"Could not parse body as Pub/Sub payload: {str(e)}")

    creds = get_google_credentials()
    service = build("gmail", "v1", credentials=creds)
    register_gmail_watch(service)

    if not pubsub_history_id:
        logger.info(
            "No historyId present in payload. Skipping sync pass; waiting for next event."
        )
        logger.info("=== Finished Inbox Janitor Ingest Execution Pass ===")
        return {
            "statusCode": 200,
            "body": json.dumps("No historyId found; pass skipped."),
        }

    processed_senders = set()
    new_message_pairs = []

    last_history_id = get_last_history_id()

    if not last_history_id:
        logger.info(
            f"No previous cursor found in DynamoDB. Initializing __SYSTEM_STATE__ to {pubsub_history_id}"
        )
        save_last_history_id(pubsub_history_id)
        logger.info("=== Finished Inbox Janitor Ingest Execution Pass ===")
        return {"statusCode": 200, "body": json.dumps("Initialized system cursor.")}

    logger.info(
        f"Fetching history records starting from cursor History ID: {last_history_id}"
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
        logger.info(
            f"Invoking {ENFORCE_LAMBDA_NAME} with {len(new_message_pairs)} record(s): {new_message_pairs}"
        )
        lambda_client.invoke(
            FunctionName=ENFORCE_LAMBDA_NAME,
            InvocationType="Event",
            Payload=json.dumps({"records": new_message_pairs}),
        )

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

        LOGS_TABLE.put_item(
            Item={
                "sender_address": sender_address,
                "timestamp_message_id": sort_key,
                "message_id": msg_id,
                "sender_name": sender_name,
                "subject": subject,
                "status": status,
                "timestamp": iso_timestamp,
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

        # Use update_item to set policy metadata AND ensure GSI keys are preserved
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
