import logging
from boto3.dynamodb.types import TypeDeserializer
from config import CANARY_TENANTS, SHADOW_MODE
from policy_engine import evaluate_sender_policy
from sqs_publisher import enqueue_enforce_records

logger = logging.getLogger()
logger.setLevel(logging.INFO)
deserializer = TypeDeserializer()


def _deserialize_image(ddb_image: dict) -> dict:
    return {k: deserializer.deserialize(v) for k, v in ddb_image.items()}


def _parse_keys(pk: str, sk: str):
    # PK format: USER#<tenant_email>#SENDER#<sender_address>
    # SK format: LOG#<iso_timestamp>#<msg_id>
    _, rest = pk.split("USER#", 1)
    tenant_email, sender_address = rest.split("#SENDER#", 1)
    msg_id = sk.rsplit("#", 1)[-1]
    return tenant_email, sender_address, msg_id


def lambda_handler(event, context):
    records = event.get("Records", [])
    if not records:
        return {"processed": 0}

    unique_pairs = set()
    insert_candidates = []

    for record in records:
        event_name = record.get("eventName")
        if event_name not in ("INSERT", "MODIFY"):
            continue

        new_image_raw = record.get("dynamodb", {}).get("NewImage")
        if not new_image_raw:
            continue

        item = _deserialize_image(new_image_raw)
        pk = item.get("PK", "")
        sk = item.get("SK", "")

        if not pk.startswith("USER#") or not sk.startswith("LOG#"):
            continue

        tenant_email, sender_address, msg_id = _parse_keys(pk, sk)
        unique_pairs.add((tenant_email, sender_address))

        if event_name == "INSERT" and item.get("in_inbox") is True:
            insert_candidates.append(
                {
                    "tenant_email": tenant_email,
                    "sender_address": sender_address,
                    "message_id": msg_id,
                    "size_bytes": int(item.get("size_bytes", 0)),
                }
            )

    # 1. Evaluate each distinct (tenant, sender) once for the entire stream batch
    evaluated_policies = {}
    for tenant_email, sender_address in unique_pairs:
        policy = evaluate_sender_policy(tenant_email, sender_address)
        evaluated_policies[(tenant_email, sender_address)] = policy

    # 2. Group qualifying INSERT candidates by tenant for SQS FIFO batching
    tenant_enqueues = {}
    for candidate in insert_candidates:
        key = (candidate["tenant_email"], candidate["sender_address"])
        if evaluated_policies.get(key) == "DELETE":
            tenant_enqueues.setdefault(candidate["tenant_email"], []).append(
                {
                    "message_id": candidate["message_id"],
                    "sender_address": candidate["sender_address"],
                    "size_bytes": candidate["size_bytes"],
                }
            )

    # 3. Dispatch to SQS (or log in Shadow Mode)
    for tenant_email, message_pairs in tenant_enqueues.items():
        is_canary = tenant_email in CANARY_TENANTS
        if SHADOW_MODE:
            logger.info(
                f"[SHADOW] Would enqueue {len(message_pairs)} record(s) for "
                f"Tenant: {tenant_email} (is_canary={is_canary}): {message_pairs}"
            )
        else:
            enqueue_enforce_records(tenant_email, message_pairs, is_canary=is_canary)

    return {"processed": len(records)}
