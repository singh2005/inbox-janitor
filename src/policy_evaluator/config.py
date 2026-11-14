import json
import os
import boto3

dynamodb = boto3.resource("dynamodb")
sqs_client = boto3.client("sqs")

TABLE_NAME = os.environ["MULTITENANT_RULES_TABLE"]
MULTI_TABLE = dynamodb.Table(TABLE_NAME)

ENFORCE_QUEUE_URL_CANARY = os.environ.get("ENFORCE_QUEUE_URL_CANARY")
ENFORCE_QUEUE_URL_PROD = os.environ.get("ENFORCE_QUEUE_URL_PROD")
CANARY_TENANTS = set(json.loads(os.environ.get("CANARY_TENANTS", "[]")))
SHADOW_MODE = os.environ.get("SHADOW_MODE", "true").lower() == "true"
