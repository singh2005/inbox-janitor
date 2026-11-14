import logging
import time
from datetime import datetime, timezone

from config import MULTI_TABLE, TTL_RETENTION_SECONDS

logger = logging.getLogger()


def get_last_history_id(tenant_email: str) -> str | None:
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


def save_last_history_id(tenant_email: str, incoming_history_id: str):
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


def process_single_message(service, tenant_email: str, msg_id: str):
    try:
        detail = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata")
            .execute()
        )

        label_ids = detail.get("labelIds", [])

        # Strict Domain Boundary: Only process messages in INBOX or TRASH (ignore SPAM and custom filters)
        has_inbox = "INBOX" in label_ids
        has_trash = "TRASH" in label_ids

        if not (has_inbox or has_trash):
            logger.info(
                f"Skipping message {msg_id}: not in INBOX or TRASH (labels: {label_ids})"
            )
            return None, 0

        headers = {
            h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])
        }

        sender_full = headers.get("From", "Unknown <unknown@example.com>")
        subject = headers.get("Subject", "(No Subject)")
        sender_address = sender_full.split("<")[-1].replace(">", "").lower().strip()
        sender_name = (
            sender_full.split("<")[0].strip() if "<" in sender_full else sender_full
        )

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

        # Update or overwrite DDB item (deduplicated by timestamp#message_id sort key)
        MULTI_TABLE.put_item(
            Item={
                "PK": f"USER#{tenant_email}#SENDER#{sender_address}",
                "SK": f"LOG#{sort_key}",
                "status": status,
                "size_bytes": size_bytes,
                "in_inbox": has_inbox,
                "ttl_timestamp": ttl_timestamp,
            }
        )

        # Signal size > 0 ONLY if currently in INBOX so index.py enqueues to SQS
        inbox_size = size_bytes if has_inbox else 0
        return sender_address, inbox_size

    except Exception as e:
        logger.error(f"Failed processing message {msg_id} for {tenant_email}: {str(e)}")
        return None, 0


def increment_incoming_count(tenant_email: str, count: int = 1):
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
