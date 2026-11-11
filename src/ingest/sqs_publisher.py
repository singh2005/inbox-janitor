import json
import logging

from config import ENFORCE_QUEUE_URL_CANARY, ENFORCE_QUEUE_URL_PROD, sqs_client

logger = logging.getLogger()


def enqueue_enforce_records(
    tenant_email: str, message_pairs: list, is_canary: bool = False
):
    target_queue_url = ENFORCE_QUEUE_URL_CANARY if is_canary else ENFORCE_QUEUE_URL_PROD

    if not message_pairs or not target_queue_url:
        return

    entries = []
    item_metadata = {}

    for idx, pair in enumerate(message_pairs):
        entry_id = str(idx)
        dedup_id = f"{tenant_email}_{pair['message_id']}"
        payload = {
            "tenant_email": tenant_email,
            "message_id": pair["message_id"],
            "sender_address": pair["sender_address"],
            "size_bytes": pair["size_bytes"],
            "is_canary": is_canary,
        }

        serialized_body = json.dumps(payload)

        entries.append(
            {
                "Id": entry_id,
                "MessageBody": serialized_body,
                "MessageDeduplicationId": dedup_id,
                "MessageGroupId": f"gmail_enforce_{tenant_email}",
            }
        )

        item_metadata[entry_id] = {
            "gmail_msg_id": pair["message_id"],
            "body": serialized_body,
        }

    for i in range(0, len(entries), 10):
        batch_chunk = entries[i : i + 10]
        try:
            response = sqs_client.send_message_batch(
                QueueUrl=target_queue_url, Entries=batch_chunk
            )

            successful = response.get("Successful", [])
            failed = response.get("Failed", [])

            for s in successful:
                entry_id = s["Id"]
                meta = item_metadata.get(entry_id, {})
                logger.info(
                    f"[ENQUEUE TRACE] SQS Accepted Entry Id={entry_id} | "
                    f"Gmail_MsgId={meta.get('gmail_msg_id')} | "
                    f"SQS_MsgId={s['MessageId']} | "
                    f"SequenceNumber={s.get('SequenceNumber')} | "
                    f"Body={meta.get('body')}"
                )

            for f in failed:
                entry_id = f["Id"]
                meta = item_metadata.get(entry_id, {})
                logger.error(
                    f"[ENQUEUE TRACE] SQS REJECTED Entry Id={entry_id} | "
                    f"Gmail_MsgId={meta.get('gmail_msg_id')} | "
                    f"Code={f['Code']} | Message={f.get('Message')} | "
                    f"SenderFault={f.get('SenderFault')}"
                )

        except Exception as e:
            logger.error(
                f"[ENQUEUE TRACE] Exception pushing batch chunk to SQS for {tenant_email}: {str(e)}"
            )
