import json
import logging
import os
from collections import defaultdict
import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
ssm_client = boto3.client("ssm")

TABLE_NAME = os.environ.get("MULTI_TABLE_NAME", "inbox-janitor-multitenant-rules-tf")
DEFAULT_TENANT_EMAIL = os.environ.get("TENANT_EMAIL", "singh2005@gmail.com")

MULTI_TABLE = dynamodb.Table(TABLE_NAME)

# Cache tenant credentials across warm Lambda container invocations
CREDENTIALS_CACHE = {}


def get_google_credentials(tenant_email):
    """
    Dynamically retrieves and caches tenant OAuth credentials from SSM Parameter Store.
    """
    if tenant_email in CREDENTIALS_CACHE:
        return CREDENTIALS_CACHE[tenant_email]

    param_name = get_tenant_param_name(tenant_email)
    logger.info(f"Fetching SSM SecureString parameter for: {param_name}")

    try:
        response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
        secret_json = json.loads(response["Parameter"]["Value"])
        scopes = ["https://www.googleapis.com/auth/gmail.modify"]

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


def get_policies_for_senders(tenant_email, senders):
    if not senders:
        return {}

    keys = [{"PK": f"USER#{tenant_email}", "SK": f"SENDER#{s}"} for s in senders]

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

        policy_map = {}
        for item in items:
            sk = item.get("SK", "")
            if sk.startswith("SENDER#"):
                sender_addr = sk.replace("SENDER#", "", 1)
                policy_map[sender_addr] = item.get("active_policy", "ALLOW")

        return policy_map
    except Exception as e:
        logger.error(f"Error batch fetching policies for {tenant_email}: {str(e)}")
        return {}


def lambda_handler(event, context):
    logger.info("=== Starting Inbox Janitor Enforcement Pass ===")

    batch_item_failures = []
    sqs_records = event.get("Records", [])

    if not sqs_records:
        logger.info("No SQS Records in event payload. Exiting cleanly.")
        return {"batchItemFailures": []}

    # Group messages by tenant_email to support multi-tenant processing
    tenant_messages = defaultdict(list)

    for record in sqs_records:
        sqs_msg_id = record["messageId"]
        try:
            payload = json.loads(record["body"])
            if isinstance(payload, dict) and "message_id" in payload:
                payload["_sqs_message_id"] = sqs_msg_id
                tenant_email = payload.get("tenant_email", DEFAULT_TENANT_EMAIL)
                tenant_messages[tenant_email].append(payload)
            else:
                logger.warning(
                    f"Malformed payload in SQS message {sqs_msg_id}. Dropping."
                )
        except Exception as e:
            logger.error(f"Failed parsing SQS record body for {sqs_msg_id}: {str(e)}")
            batch_item_failures.append({"itemIdentifier": sqs_msg_id})

    total_trashed_overall = 0
    total_bytes_trashed_overall = 0

    # Process per tenant
    for tenant_email, messages in tenant_messages.items():
        distinct_senders = {msg["sender_address"] for msg in messages}
        policy_map = get_policies_for_senders(tenant_email, distinct_senders)

        messages_to_trash = [
            msg
            for msg in messages
            if policy_map.get(msg["sender_address"], "ALLOW") == "DELETE"
        ]

        if not messages_to_trash:
            continue

        try:
            creds = get_google_credentials(tenant_email)
            service = build("gmail", "v1", credentials=creds)

            message_ids = [msg["message_id"] for msg in messages_to_trash]
            logger.info(
                f"Batch trashing {len(message_ids)} message(s) for tenant {tenant_email}"
            )

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
                    service.users().messages().batchModify(
                        userId="me", body=body
                    ).execute()
                    total_trashed_overall += len(chunk_ids)
                    total_bytes_trashed_overall += sum(
                        msg.get("size_bytes", 0) for msg in chunk_msgs
                    )
                except Exception as e:
                    logger.error(
                        f"Error during batchModify execution for tenant {tenant_email}: {str(e)}"
                    )
                    for msg in chunk_msgs:
                        batch_item_failures.append(
                            {"itemIdentifier": msg["_sqs_message_id"]}
                        )
        except Exception as e:
            logger.error(
                f"Failed resolving service or processing enforcement for {tenant_email}: {str(e)}"
            )
            for msg in messages_to_trash:
                batch_item_failures.append({"itemIdentifier": msg["_sqs_message_id"]})

    if total_trashed_overall > 0:
        update_global_metrics(total_trashed_overall, total_bytes_trashed_overall)

    logger.info(
        f"=== Enforcement Complete. Successfully trashed {total_trashed_overall} messages overall. Failures: {len(batch_item_failures)} ==="
    )

    return {"batchItemFailures": batch_item_failures}


def get_tenant_param_name(tenant_email):
    """
    Converts raw tenant email to a valid SSM Parameter Store path.
    Example: singh2005@gmail.com -> /inbox-janitor/tenants/singh2005-at-gmail-com/credentials
    """
    sanitized_id = tenant_email.replace("@", "-at-").replace(".", "-")
    return f"/inbox-janitor/tenants/{sanitized_id}/credentials"
