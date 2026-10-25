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

RULES_TABLE_NAME = os.environ.get(
    "RULES_TABLE", "inbox-janitor-active-routing-rules-tf"
)
SECRET_ARN = os.environ.get("SECRET_ARN")

RULES_TABLE = dynamodb.Table(RULES_TABLE_NAME)


def get_google_credentials():
    response = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret_json = json.loads(response["SecretString"])

    scopes = [
        "https://www.googleapis.com/auth/gmail.metadata",
        "https://www.googleapis.com/auth/gmail.labels",
    ]

    return Credentials(
        token=None,
        refresh_token=secret_json["refresh_token"],
        client_id=secret_json["client_id"],
        client_secret=secret_json["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=scopes,
    )


def increment_trashed_counts(trashed_senders_map):
    total_trashed_in_pass = sum(trashed_senders_map.values())
    if total_trashed_in_pass <= 0:
        return

    # 1. Update Global Metrics Counter (__GLOBAL_METRICS__)
    try:
        RULES_TABLE.update_item(
            Key={"sender_address": "__GLOBAL_METRICS__"},
            UpdateExpression="ADD total_trashed :val",
            ExpressionAttributeValues={":val": total_trashed_in_pass},
        )
        logger.info(f"Updated __GLOBAL_METRICS__ by +{total_trashed_in_pass}")
    except Exception as e:
        logger.error(f"Failed updating __GLOBAL_METRICS__: {str(e)}")

    # 2. Update Per-Sender Counts & GSI Partition Key (entity_type = 'RULE')
    for sender, count in trashed_senders_map.items():
        if count <= 0:
            continue
        try:
            RULES_TABLE.update_item(
                Key={"sender_address": sender},
                UpdateExpression="SET entity_type = :et ADD trashed_count :val",
                ExpressionAttributeValues={":et": "RULE", ":val": count},
            )
            logger.info(f"Updated {sender}: trashed_count +{count}, entity_type=RULE")
        except Exception as e:
            logger.error(f"Failed updating stats for {sender}: {str(e)}")


def lambda_handler(event, context):
    logger.info("=== Starting Inbox Janitor Enforcement Pass ===")

    sqs_records = event.get("Records", [])
    if not sqs_records:
        logger.info("No SQS Records in event payload. Exiting cleanly.")
        return {"statusCode": 200, "body": json.dumps("No messages to process.")}

    messages_to_process = []
    distinct_senders = set()

    # Extract payloads passed from SQS Event Source Mapping
    for record in sqs_records:
        try:
            payload = json.loads(record["body"])
            if isinstance(payload, dict) and "message_id" in payload:
                messages_to_process.append(payload)
                distinct_senders.add(payload["sender_address"])
        except Exception as e:
            logger.error(f"Failed parsing SQS record body: {str(e)}")

    if not messages_to_process:
        return {"statusCode": 200, "body": json.dumps("No valid messages parsed.")}

    creds = get_google_credentials()
    service = build("gmail", "v1", credentials=creds)

    # Fetch active sender policies
    policy_map = get_policies_for_senders(distinct_senders)

    # Filter messages whose active policy is 'DELETE'
    messages_to_trash = [
        msg
        for msg in messages_to_process
        if policy_map.get(msg["sender_address"], "ALLOW") == "DELETE"
    ]

    trashed_count = 0
    trashed_senders_map = {}

    if messages_to_trash:
        message_ids = [msg["message_id"] for msg in messages_to_trash]
        logger.info(f"Batch trashing {len(message_ids)} message(s) via batchModify")

        # Process in batches of 1000 (Gmail API hard limit for batchModify)
        batch_size = 1000
        for i in range(0, len(message_ids), batch_size):
            chunk = message_ids[i : i + batch_size]
            body = {
                "ids": chunk,
                "addLabelIds": ["TRASH"],
                "removeLabelIds": ["INBOX"],
            }
            try:
                service.users().messages().batchModify(userId="me", body=body).execute()
                trashed_count += len(chunk)
            except Exception as e:
                logger.error(f"Error during batchModify execution: {str(e)}")

        # Build sender metrics map for successfully processed messages
        if trashed_count > 0:
            for msg in messages_to_trash:
                sender = msg.get("sender_address", "unknown")
                trashed_senders_map[sender] = trashed_senders_map.get(sender, 0) + 1

            increment_trashed_counts(trashed_senders_map)

    logger.info(f"=== Enforcement Complete. Trashed {trashed_count} messages. ===")
    return {
        "statusCode": 200,
        "body": json.dumps(f"Trashed {trashed_count} messages."),
    }


def get_policies_for_senders(senders):
    if not senders:
        return {}

    keys = [{"sender_address": s} for s in senders]
    try:
        response = dynamodb.batch_get_item(
            RequestItems={
                RULES_TABLE_NAME: {
                    "Keys": keys,
                    "ProjectionExpression": "sender_address, active_policy",
                }
            }
        )
        items = response.get("Responses", {}).get(RULES_TABLE_NAME, [])
        return {
            item["sender_address"]: item.get("active_policy", "ALLOW") for item in items
        }
    except Exception as e:
        logger.error(f"Error batch fetching policies: {str(e)}")
        return {}
