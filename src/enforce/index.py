import json
import logging
import os
import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")

TABLE_NAME = os.environ.get("MULTI_TABLE_NAME", "inbox-janitor-multitenant-rules-tf")
SECRET_ARN = os.environ.get("SECRET_ARN")
TENANT_EMAIL = os.environ.get("TENANT_EMAIL", "singh2005@gmail.com")

MULTI_TABLE = dynamodb.Table(TABLE_NAME)


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


def update_global_metrics(total_trashed_count, total_bytes_trashed):
    """
    Atomic update for global metrics summary targeting PK = GLOBAL, SK = METRICS.
    """
    if total_trashed_count <= 0:
        return

    try:
        MULTI_TABLE.update_item(
            Key={"PK": "GLOBAL", "SK": "METRICS"},
            UpdateExpression="ADD total_trashed :c, total_bytes_trashed :b",
            ExpressionAttributeValues={
                ":c": total_trashed_count,
                ":b": total_bytes_trashed,
            },
        )
        mb_saved = total_bytes_trashed / (1024 * 1024)
        logger.info(
            f"Updated GLOBAL/METRICS by +{total_trashed_count} emails, "
            f"+{total_bytes_trashed} bytes ({mb_saved:.2f} MB)"
        )
    except Exception as e:
        logger.error(f"Failed updating GLOBAL/METRICS: {str(e)}")


def lambda_handler(event, context):
    logger.info("=== Starting Inbox Janitor Enforcement Pass ===")

    batch_item_failures = []
    sqs_records = event.get("Records", [])

    if not sqs_records:
        logger.info("No SQS Records in event payload. Exiting cleanly.")
        return {"batchItemFailures": []}

    messages_to_process = []
    distinct_senders = set()

    for record in sqs_records:
        sqs_msg_id = record["messageId"]
        try:
            payload = json.loads(record["body"])
            if isinstance(payload, dict) and "message_id" in payload:
                payload["_sqs_message_id"] = sqs_msg_id
                messages_to_process.append(payload)
                distinct_senders.add(payload["sender_address"])
            else:
                logger.warning(
                    f"Malformed payload in SQS message {sqs_msg_id}. Dropping."
                )
        except Exception as e:
            logger.error(f"Failed parsing SQS record body for {sqs_msg_id}: {str(e)}")
            batch_item_failures.append({"itemIdentifier": sqs_msg_id})

    if not messages_to_process:
        return {"batchItemFailures": batch_item_failures}

    # Fetch active sender policies using composite keys
    policy_map = get_policies_for_senders(distinct_senders)

    # Filter messages whose active policy is 'DELETE'
    messages_to_trash = [
        msg
        for msg in messages_to_process
        if policy_map.get(msg["sender_address"], "ALLOW") == "DELETE"
    ]

    if messages_to_trash:
        creds = get_google_credentials()
        service = build("gmail", "v1", credentials=creds)

        message_ids = [msg["message_id"] for msg in messages_to_trash]
        logger.info(f"Batch trashing {len(message_ids)} message(s) via batchModify")

        trashed_count = 0
        trashed_bytes = 0

        # Process in chunks of 1000 (Gmail API hard limit for batchModify)
        batch_size = 1000
        for i in range(0, len(message_ids), batch_size):
            chunk_msgs = messages_to_trash[i : i + batch_size]
            chunk_ids = [msg["message_id"] for msg in chunk_msgs]

            body = {
                "ids": chunk_ids,
                "addLabelIds": ["TRASH"],
                "removeLabelIds": ["INBOX"],
            }

            try:
                service.users().messages().batchModify(userId="me", body=body).execute()
                trashed_count += len(chunk_ids)
                trashed_bytes += sum(msg.get("size_bytes", 0) for msg in chunk_msgs)
            except Exception as e:
                logger.error(f"Error during batchModify execution for chunk: {str(e)}")
                for msg in chunk_msgs:
                    batch_item_failures.append(
                        {"itemIdentifier": msg["_sqs_message_id"]}
                    )

        if trashed_count > 0:
            update_global_metrics(trashed_count, trashed_bytes)

        logger.info(
            f"=== Enforcement Complete. Successfully trashed {trashed_count}/"
            f"{len(messages_to_trash)} messages. Failures: {len(batch_item_failures)} ==="
        )

    return {"batchItemFailures": batch_item_failures}


def get_policies_for_senders(senders):
    if not senders:
        return {}

    keys = [{"PK": f"USER#{TENANT_EMAIL}", "SK": f"SENDER#{s}"} for s in senders]

    try:
        response = dynamodb.batch_get_item(
            RequestItems={
                TABLE_NAME: {
                    "Keys": keys,
                    "ProjectionExpression": "SK, active_policy",
                }
            }
        )
        items = response.get("Responses", {}).get(TABLE_NAME, [])

        # Map SK back to the sender_address (strip "SENDER#" prefix)
        policy_map = {}
        for item in items:
            sk = item.get("SK", "")
            if sk.startswith("SENDER#"):
                sender_addr = sk.replace("SENDER#", "", 1)
                policy_map[sender_addr] = item.get("active_policy", "ALLOW")

        return policy_map
    except Exception as e:
        logger.error(f"Error batch fetching policies: {str(e)}")
        return {}
