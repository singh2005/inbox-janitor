import json
import logging
import os
import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')

RULES_TABLE_NAME = os.environ.get('RULES_TABLE', 'inbox-janitor-active-routing-rules-tf')
SECRET_ARN = os.environ.get('SECRET_ARN')

RULES_TABLE = dynamodb.Table(RULES_TABLE_NAME)

def get_google_credentials():
    response = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret_json = json.loads(response['SecretString'])
    scopes = ['https://www.googleapis.com/auth/gmail.modify']

    return Credentials(
        token=None,
        refresh_token=secret_json['refresh_token'],
        client_id=secret_json['client_id'],
        client_secret=secret_json['client_secret'],
        token_uri='https://oauth2.googleapis.com/token',
        scopes=scopes,
    )

def lambda_handler(event, context):
    logger.info('=== Starting Inbox Janitor Enforcement Pass ===')

    # Expecting records as dicts: [{"message_id": "123", "sender_address": "user@example.com"}]
    # Fallback support for legacy raw string lists: ["123", "456"]
    raw_records = event.get('records', event.get('message_ids', []))
    if not raw_records:
        logger.info('No records in event payload. Exiting cleanly.')
        return {'statusCode': 200, 'body': json.dumps('No messages to process.')}

    creds = get_google_credentials()
    service = build('gmail', 'v1', credentials=creds)

    # 1. Standardize records format & extract distinct senders
    messages_to_process = []
    distinct_senders = set()

    for item in raw_records:
        if isinstance(item, dict):
            messages_to_process.append(item)
            distinct_senders.add(item['sender_address'])
        else:
            # Fallback for old string payload format (inspect sender manually)
            sender = fetch_sender_from_gmail(service, item)
            if sender:
                messages_to_process.append({'message_id': item, 'sender_address': sender})
                distinct_senders.add(sender)

    if not messages_to_process:
        return {'statusCode': 200, 'body': json.dumps('No valid messages parsed.')}

    # 2. Batch fetch policies from DynamoDB in ONE call
    policy_map = get_policies_for_senders(distinct_senders)

    # 3. Filter messages whose active policy is 'DELETE'
    messages_to_trash = [
        msg['message_id']
        for msg in messages_to_process
        if policy_map.get(msg['sender_address'], 'ALLOW') == 'DELETE'
    ]

    # 4. Batch Trash via Gmail API in ONE call
    trashed_count = 0
    if messages_to_trash:
        logger.info(f"Batch trashing {len(messages_to_trash)} message(s): {messages_to_trash}")
        service.users().messages().batchTrash(
            userId='me',
            body={'ids': messages_to_trash}
        ).execute()
        trashed_count = len(messages_to_trash)

    logger.info(f'=== Enforcement Complete. Trashed {trashed_count} messages. ===')
    return {
        'statusCode': 200,
        'body': json.dumps(f'Trashed {trashed_count} messages.'),
    }

def get_policies_for_senders(senders):
    """Batch reads active routing rules from DynamoDB for a set of sender addresses."""
    if not senders:
        return {}

    keys = [{'sender_address': s} for s in senders]
    try:
        response = dynamodb.batch_get_item(
            RequestItems={
                RULES_TABLE_NAME: {
                    'Keys': keys,
                    'ProjectionExpression': 'sender_address, active_policy'
                }
            }
        )
        items = response.get('Responses', {}).get(RULES_TABLE_NAME, [])
        return {item['sender_address']: item.get('active_policy', 'ALLOW') for item in items}
    except Exception as e:
        logger.error(f"Error batch fetching policies: {str(e)}")
        return {}

def fetch_sender_from_gmail(service, msg_id):
    """Fallback helper for un-migrated raw message_id strings."""
    try:
        detail = service.users().messages().get(userId='me', id=msg_id, format='metadata').execute()
        headers = {h['name']: h['value'] for h in detail.get('payload', {}).get('headers', [])}
        sender_full = headers.get('From', '')
        return sender_full.split('<')[-1].replace('>', '').lower().strip()
    except Exception as e:
        logger.error(f"Error fetching sender metadata for {msg_id}: {str(e)}")
        return None