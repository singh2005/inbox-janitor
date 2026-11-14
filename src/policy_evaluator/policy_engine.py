import logging
from datetime import datetime, timezone
from config import MULTI_TABLE, SHADOW_MODE

logger = logging.getLogger()


def evaluate_sender_policy(tenant_email: str, sender_address: str) -> str:
    query_resp = MULTI_TABLE.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{tenant_email}#SENDER#{sender_address}",
            ":sk_prefix": "LOG#",
        },
        ScanIndexForward=False,
        Limit=6,
    )

    items = query_resp.get("Items", [])
    total_sampled = len(items)
    unread_count = sum(1 for item in items if item.get("status") == "UNREAD")

    policy = "DELETE" if (total_sampled == 6 and unread_count == 6) else "ALLOW"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if SHADOW_MODE:
        logger.info(
            f"[SHADOW] Tenant: {tenant_email} | Sender: {sender_address} | "
            f"Window: {unread_count}/{total_sampled} UNREAD | Would set Policy: {policy}"
        )
        return policy

    MULTI_TABLE.update_item(
        Key={"PK": f"USER#{tenant_email}", "SK": f"SENDER#{sender_address}"},
        UpdateExpression=(
            "SET unread_streak = :us, active_policy = :ap, last_evaluated = :le, sender_address = :sa "
            "REMOVE sender_name, trashed_count, entity_type"
        ),
        ExpressionAttributeValues={
            ":us": f"{unread_count}/{total_sampled}",
            ":ap": policy,
            ":le": now_iso,
            ":sa": sender_address,
        },
    )
    logger.info(
        f"Tenant: {tenant_email} | Sender: {sender_address} | "
        f"Window: {unread_count}/{total_sampled} UNREAD | Policy: {policy}"
    )
    return policy
