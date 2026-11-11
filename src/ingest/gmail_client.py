import json
import logging
import time
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import GCP_PUBSUB_TOPIC, MULTI_TABLE, ssm_client

logger = logging.getLogger()

CREDENTIALS_CACHE = {}


def get_tenant_param_name(tenant_email: str) -> str:
    sanitized_id = tenant_email.replace("@", "-at-").replace(".", "-")
    return f"/inbox-janitor/tenants/{sanitized_id}/credentials"


def get_google_credentials(tenant_email: str) -> Credentials:
    if tenant_email in CREDENTIALS_CACHE:
        return CREDENTIALS_CACHE[tenant_email]

    param_name = get_tenant_param_name(tenant_email)
    logger.info(f"Fetching SSM SecureString parameter for: {param_name}")

    try:
        response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
        secret_json = json.loads(response["Parameter"]["Value"])
        scopes = ["https://www.googleapis.com/auth/gmail.metadata"]

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


def build_gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def check_and_renew_gmail_watch(service, tenant_email: str):
    if not GCP_PUBSUB_TOPIC:
        logger.error("GCP_PUBSUB_TOPIC environment variable is not set!")
        return

    now_ms = int(time.time() * 1000)
    renew_buffer_ms = 24 * 60 * 60 * 1000

    try:
        resp = MULTI_TABLE.get_item(
            Key={"PK": f"USER#{tenant_email}", "SK": "SYSTEM_STATE"}
        )
        raw_exp = resp["Item"].get("watch_expiration_ms") if "Item" in resp else None
        current_expiration = int(raw_exp) if raw_exp is not None else None

        if current_expiration and (current_expiration - now_ms > renew_buffer_ms):
            logger.info(f"Gmail Watch active for {tenant_email}. Skipping renew.")
            return

        request_body = {"topicName": GCP_PUBSUB_TOPIC}
        response = service.users().watch(userId="me", body=request_body).execute()
        new_expiration_ms = int(response.get("expiration", 0))

        MULTI_TABLE.update_item(
            Key={"PK": f"USER#{tenant_email}", "SK": "SYSTEM_STATE"},
            UpdateExpression="SET watch_expiration_ms = :exp, updated_at = :ua",
            ExpressionAttributeValues={
                ":exp": new_expiration_ms,
                ":ua": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as e:
        logger.error(f"Failed renew_gmail_watch for {tenant_email}: {str(e)}")
