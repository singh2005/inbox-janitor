import os
import boto3

TABLE_NAME = os.environ.get(
    "MULTITENANT_RULES_TABLE", "inbox-janitor-multitenant-rules-tf"
)
GCP_PUBSUB_TOPIC = os.environ.get("GCP_PUBSUB_TOPIC")
ENFORCE_QUEUE_URL_CANARY = os.environ.get("ENFORCE_QUEUE_URL_CANARY")
ENFORCE_QUEUE_URL_PROD = os.environ.get("ENFORCE_QUEUE_URL_PROD")
DEFAULT_TENANT_EMAIL = os.environ.get("TENANT_EMAIL", "singh2005@gmail.com")

TTL_RETENTION_SECONDS = 3888000

dynamodb = boto3.resource("dynamodb")
ssm_client = boto3.client("ssm")
sqs_client = boto3.client("sqs")

MULTI_TABLE = dynamodb.Table(TABLE_NAME)
