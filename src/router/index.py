import base64
import json
import os
import time
import boto3

lambda_client = boto3.client("lambda")
dynamodb = boto3.resource("dynamodb")

INGEST_FUNCTION_NAME = os.environ["INGEST_FUNCTION_NAME"]
TABLE_NAME = os.environ["MULTITENANT_RULES_TABLE"]

# In-memory local cache across warm execution contexts
CANARY_CACHE = set()
CACHE_EXPIRATION = 0
CACHE_TTL_SECONDS = 300  # Refresh cache every 5 minutes


def get_canary_tenants():
    global CANARY_CACHE, CACHE_EXPIRATION
    now = time.time()
    if now > CACHE_EXPIRATION:
        try:
            table = dynamodb.Table(TABLE_NAME)
            response = table.get_item(Key={"PK": "CONFIG", "SK": "CANARY_TENANTS"})
            CANARY_CACHE = set(response.get("Item", {}).get("tenants", []))
            CACHE_EXPIRATION = now + CACHE_TTL_SECONDS
        except Exception as e:
            print(f"Failed to refresh canary cache: {e}")
    return CANARY_CACHE


def lambda_handler(event, context):
    batch_failures = []
    canary_set = get_canary_tenants()

    for record in event.get("Records", []):
        msg_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            raw_data = body.get("message", {}).get("data", "")

            if raw_data:
                decoded_bytes = base64.b64decode(raw_data)
                payload = json.loads(decoded_bytes.decode("utf-8"))
                tenant_email = payload.get("emailAddress", "")
            else:
                payload = body
                tenant_email = ""

            # Check if tenant is canary
            is_canary = tenant_email in canary_set
            target_alias = "CANARY" if is_canary else "PROD"

            # Enrich payload with canary status flag
            payload["is_canary"] = is_canary

            # Asynchronous invocation to target ingest alias
            lambda_client.invoke(
                FunctionName=f"{INGEST_FUNCTION_NAME}:{target_alias}",
                InvocationType="Event",
                Payload=json.dumps(payload),
            )

        except Exception as e:
            print(f"Error processing message {msg_id}: {e}")
            batch_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_failures}
