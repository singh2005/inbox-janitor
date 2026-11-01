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
ssm_client = boto3.client("ssm")
sqs_client = boto3.client("sqs")

TABLE_NAME = os.environ.get("MULTI_TABLE_NAME", "inbox-janitor-multitenant-rules-tf")
GCP_PUBSUB_TOPIC = os.environ.get("GCP_PUBSUB_TOPIC")
ENFORCE_QUEUE_URL = os.environ.get("ENFORCE_QUEUE_URL")
DEFAULT_TENANT_EMAIL = os.environ.get("TENANT_EMAIL", "singh2005@gmail.com")

MULTI_TABLE = dynamodb.Table(TABLE_NAME)
TTL_RETENTION_SECONDS = 3888000
CREDENTIALS_CACHE = {}


def get_google_credentials(tenant_email):
    if tenant_email in CREDENTIALS_CACHE:
        return CREDENTIALS_CACHE[tenant_email]

    param_name = get_tenant_param_name(tenant_email)
    logger.info(f"Fetching SSM SecureString parameter for: {param_name}")

    try:
        response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
        secret_json = json.loads(response["Parameter"]["Value"])
        scopes = ["https://www.googleapis.com/auth/gmail.metadata"]

        creds = Credentials(
            token=None,
            refresh_token=secret_json["refresh_token"],
            client_id=secret_json["client_id"],
            client_secret=secret_json["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=scopes,
        )
        CREDENTIALS_CACHE[tenant_email] = creds
        return creds
    except Exception as e:
        logger.error(
            f"Failed retrieving SSM credentials for tenant {tenant_email}: {str(e)}"
        )
        raise e


def check_and_renew_gmail_watch(service, tenant_email):
    if not GCP_PUBSUB_TOPIC:
        logger.error("GCP_PUBSUB_TOPIC environment variable is not set!")
        return

    now_ms = int(time.time() * 1000)
    renew_buffer_ms = 24 * 60 * 60 * 1000

    try:
        resp = MULTI_TABLE.get_item(
            Key={"PK": f"USER#{tenant_email}", "SK": "SYSTEM_STATE"}
        )
        raw_exp = resp["Item"].get("watch_expiration_ms") if "Item" in resp else None
        current_expiration = int(raw_exp) if raw_exp is not None else None

        if current_expiration and (current_expiration - now_ms > renew_buffer_ms):
            logger.info(f"Gmail Watch active for {tenant_email}. Skipping renew.")
            return

        request_body = {"topicName": GCP_PUBSUB_TOPIC}
        response = service.users().watch(userId="me", body=request_body).execute()
        new_expiration_ms = int(response.get("expiration", 0))

        MULTI_TABLE.update_item(
            Key={"PK": f"USER#{tenant_email}", "SK": "SYSTEM_STATE"},
            UpdateExpression="SET watch_expiration_ms = :exp, updated_at = :ua",
            ExpressionAttributeValues={
                ":exp": new_expiration_ms,
                ":ua": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as e:
        logger.error(f"Failed renew_gmail_watch for {tenant_email}: {str(e)}")


def get_last_history_id(tenant_email):
    try:
        resp = MULTI_TABLE.get_item(
            Key={"PK": f"USER#{tenant_email}", "SK": "SYSTEM_STATE"}
        )
        if "Item" in resp:
            val = resp["Item"].get("last_history_id")
            return str(val) if val is not None else None
    except Exception as e:
        logger.warning(f"Could not read last_history_id for {tenant_email}: {str(e)}")
    return None


def save_last_history_id(tenant_email, incoming_history_id):
    try:
        numeric_id = int(incoming_history_id)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        MULTI_TABLE.update_item(
            Key={"PK": f"USER#{tenant_email}", "SK": "SYSTEM_STATE"},
            UpdateExpression="SET last_history_id = :new_id, updated_at = :ua",
            ConditionExpression="attribute_not_exists(last_history_id) OR last_history_id < :new_id",
            ExpressionAttributeValues={
                ":new_id": numeric_id,
                ":ua": now_iso,
            },
        )
    except Exception as e:
        logger.error(f"Failed saving last_history_id for {tenant_email}: {str(e)}")


def enqueue_enforce_records(tenant_email, message_pairs):
    if not message_pairs or not ENFORCE_QUEUE_URL:
        return

    entries = []
    for idx, pair in enumerate(message_pairs):
        payload = {
            "tenant_email": tenant_email,
            "message_id": pair["message_id"],
            "sender_address": pair["sender_address"],
            "size_bytes": pair["size_bytes"],
        }
        entries.append(
            {
                "Id": str(idx),
                "MessageBody": json.dumps(payload),
                "MessageDeduplicationId": f"{tenant_email}_{pair['message_id']}",
                "MessageGroupId": f"gmail_enforce_{tenant_email}",
            }
        )

    for i in range(0, len(entries), 10):
        batch_chunk = entries[i : i + 10]
        try:
            sqs_client.send_message_batch(
                QueueUrl=ENFORCE_QUEUE_URL, Entries=batch_chunk
            )
        except Exception as e:
            logger.error(
                f"Failed pushing batch chunk to SQS for {tenant_email}: {str(e)}"
            )


def increment_incoming_count(tenant_email, count=1):
    """
    Atomically increments total_incoming_emails counter on tenant and global metrics.
    """
    if count <= 0:
        return

    for pk in [f"USER#{tenant_email}", "GLOBAL"]:
        try:
            MULTI_TABLE.update_item(
                Key={"PK": pk, "SK": "METRICS"},
                UpdateExpression="ADD total_incoming_emails :c",
                ExpressionAttributeValues={":c": count},
            )
        except Exception as e:
            logger.error(f"Failed incrementing incoming count for {pk}: {str(e)}")


def lambda_handler(event, context):
    logger.info("=== Starting Inbox Janitor Ingest Execution Pass ===")

    pubsub_history_id = None
    tenant_email = DEFAULT_TENANT_EMAIL

    if "body" in event:
        try:
            body = json.loads(event["body"])
            if "message" in body and "data" in body["message"]:
                decoded_data = base64.b64decode(body["message"]["data"]).decode("utf-8")
                pubsub_event = json.loads(decoded_data)
                pubsub_history_id = pubsub_event.get("historyId")
                extracted_email = pubsub_event.get("emailAddress")
                if extracted_email:
                    tenant_email = extracted_email
        except Exception as e:
            logger.warning(f"Could not parse body as Pub/Sub payload: {str(e)}")

    creds = get_google_credentials(tenant_email)
    service = build("gmail", "v1", credentials=creds)
    check_and_renew_gmail_watch(service, tenant_email)

    if not pubsub_history_id:
        return {
            "statusCode": 200,
            "body": json.dumps("No historyId found; pass skipped."),
        }

    processed_senders = set()
    new_message_pairs = []

    last_history_id = get_last_history_id(tenant_email)
    if not last_history_id:
        save_last_history_id(tenant_email, pubsub_history_id)
        return {"statusCode": 200, "body": json.dumps("Initialized system cursor.")}

    try:
        history_response = (
            service.users()
            .history()
            .list(userId="me", startHistoryId=str(last_history_id))
            .execute()
        )

        history_records = history_response.get("history", [])
        new_incoming_count = 0

        for record in history_records:
            if "messagesAdded" in record:
                for item in record["messagesAdded"]:
                    msg_id = item["message"]["id"]
                    sender, size_bytes = process_single_message(
                        service, tenant_email, msg_id
                    )
                    if sender:
                        processed_senders.add(sender)
                        new_message_pairs.append(
                            {
                                "message_id": msg_id,
                                "sender_address": sender,
                                "size_bytes": size_bytes,
                            }
                        )
                        new_incoming_count += 1

            for label_event in record.get("labelsRemoved", []) + record.get(
                "labelsAdded", []
            ):
                msg_id = label_event["message"]["id"]
                sender, _ = process_single_message(service, tenant_email, msg_id)
                if sender:
                    processed_senders.add(sender)

        # Direct increment for new messages added in this pass
        if new_incoming_count > 0:
            increment_incoming_count(tenant_email, count=new_incoming_count)

        save_last_history_id(tenant_email, pubsub_history_id)

    except Exception as e:
        logger.error(f"Error querying Gmail History API for {tenant_email}: {str(e)}")

    if processed_senders:
        evaluate_and_update_policies(tenant_email, processed_senders)

    if new_message_pairs:
        enqueue_enforce_records(tenant_email, new_message_pairs)

    logger.info("=== Finished Inbox Janitor Ingest Execution Pass ===")
    return {"statusCode": 200, "body": json.dumps("Success")}


def process_single_message(service, tenant_email, msg_id):
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
        raw_size = detail.get("sizeEstimate")
        size_bytes = int(raw_size) if raw_size is not None else 0

        internal_date_ms = int(detail.get("internalDate", 0))
        iso_timestamp = (
            datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        sort_key = f"{iso_timestamp}#{msg_id}"
        ttl_timestamp = int(time.time()) + TTL_RETENTION_SECONDS

        MULTI_TABLE.put_item(
            Item={
                "PK": f"USER#{tenant_email}#SENDER#{sender_address}",
                "SK": f"LOG#{sort_key}",
                "message_id": msg_id,
                "sender_address": sender_address,
                "sender_name": sender_name,
                "subject": subject,
                "status": status,
                "timestamp": iso_timestamp,
                "ttl_timestamp": ttl_timestamp,
            }
        )
        return sender_address, size_bytes
    except Exception as e:
        logger.error(f"Failed processing message {msg_id} for {tenant_email}: {str(e)}")
        return None, 0


def evaluate_and_update_policies(tenant_email, processed_senders):
    for address in processed_senders:
        query_resp = MULTI_TABLE.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{tenant_email}#SENDER#{address}",
                ":sk_prefix": "LOG#",
            },
            ScanIndexForward=False,
            Limit=6,
        )

        items = query_resp.get("Items", [])
        total_sampled = len(items)
        unread_count = sum(1 for item in items if item.get("status") == "UNREAD")

        policy = "DELETE" if (total_sampled == 6 and unread_count == 6) else "ALLOW"
        sender_name = items[0].get("sender_name", "Unknown") if items else "Unknown"
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        MULTI_TABLE.update_item(
            Key={"PK": f"USER#{tenant_email}", "SK": f"SENDER#{address}"},
            UpdateExpression=(
                "SET sender_name = :sn, unread_streak = :us, active_policy = :ap, last_evaluated = :le, sender_address = :sa "
                "REMOVE trashed_count, entity_type"
            ),
            ExpressionAttributeValues={
                ":sn": sender_name,
                ":us": f"{unread_count}/{total_sampled}",
                ":ap": policy,
                ":le": now_iso,
                ":sa": address,
            },
        )


def get_tenant_param_name(tenant_email):
    sanitized_id = tenant_email.replace("@", "-at-").replace(".", "-")
    return f"/inbox-janitor/tenants/{sanitized_id}/credentials"
