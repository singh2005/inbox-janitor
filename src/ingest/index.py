import json
import logging

from config import DEFAULT_TENANT_EMAIL
from gmail_client import (
    build_gmail_service,
    check_and_renew_gmail_watch,
    get_google_credentials,
)
from storage import (
    get_last_history_id,
    increment_incoming_count,
    process_single_message,
    save_last_history_id,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def parse_router_payload(event: dict):
    tenant_email = (
        event.get("emailAddress")
        or event.get("tenant_email")
        or event.get("email")
        or DEFAULT_TENANT_EMAIL
    )
    pubsub_history_id = event.get("historyId")
    is_canary = event.get("is_canary", False)

    return tenant_email, pubsub_history_id, is_canary


def lambda_handler(event, context):
    logger.info(f"=== Received Event from Router: {json.dumps(event)} ===")

    tenant_email, pubsub_history_id, is_canary = parse_router_payload(event)
    logger.info(
        f"Target tenant: {tenant_email} | historyId: {pubsub_history_id} | is_canary: {is_canary}"
    )

    creds = get_google_credentials(tenant_email)
    service = build_gmail_service(creds)
    check_and_renew_gmail_watch(service, tenant_email)

    if not pubsub_history_id:
        logger.info("No historyId present in payload. Skipping history sync.")
        return {"statusCode": 200, "body": json.dumps("No historyId found.")}

    last_history_id = get_last_history_id(tenant_email)
    if not last_history_id:
        save_last_history_id(tenant_email, pubsub_history_id)
        logger.info(
            f"Initialized system cursor for {tenant_email} at historyId {pubsub_history_id}."
        )
        return {"statusCode": 200, "body": json.dumps("Initialized cursor.")}

    try:
        history_response = (
            service.users()
            .history()
            .list(userId="me", startHistoryId=str(last_history_id))
            .execute()
        )

        logger.info(f"logging history_response >>> {json.dumps(history_response)}")

        history_records = history_response.get("history", [])
        seen_msg_ids = set()
        new_incoming_count = 0

        for h_record in history_records:
            # 1. New Message Arrivals
            for item in h_record.get("messagesAdded", []):
                msg_id = item["message"]["id"]
                if msg_id in seen_msg_ids:
                    continue
                seen_msg_ids.add(msg_id)

                if process_single_message(service, tenant_email, msg_id):
                    new_incoming_count += 1

            # 2. Label State Sync (READ / UNREAD toggles in INBOX or TRASH)
            for label_event in h_record.get("labelsRemoved", []) + h_record.get(
                "labelsAdded", []
            ):
                msg_id = label_event["message"]["id"]
                if msg_id in seen_msg_ids:
                    continue
                seen_msg_ids.add(msg_id)

                process_single_message(service, tenant_email, msg_id)

        if new_incoming_count > 0:
            increment_incoming_count(tenant_email, count=new_incoming_count)

        save_last_history_id(tenant_email, pubsub_history_id)

    except Exception as e:
        logger.error(f"Error querying Gmail History API for {tenant_email}: {str(e)}")

    logger.info("=== Finished Ingest Pass ===")
    return {"statusCode": 200, "body": json.dumps("Success")}
