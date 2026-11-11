import logging
from datetime import datetime, timezone

from config import MULTI_TABLE

logger = logging.getLogger()


def evaluate_and_update_policies(tenant_email: str, processed_senders: set):
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
        logger.info(
            f"Tenant: {tenant_email} | Sender: {address} | Window: {unread_count}/{total_sampled} UNREAD | Policy: {policy}"
        )
