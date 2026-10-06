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

# Read environment variables injected by Terraform
RULES_TABLE_NAME = os.environ.get('RULES_TABLE', 'inbox-janitor-active-routing-rules-tf')
SECRET_ARN = os.environ.get('SECRET_ARN')

RULES_TABLE = dynamodb.Table(RULES_TABLE_NAME)

def get_google_credentials():
  """Fetch OAuth user credentials from Secrets Manager using Secret ARN."""
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

  message_ids = event.get('message_ids', [])
  if not message_ids:
    logger.info('No message_ids in event payload. Exiting cleanly.')
    return {'statusCode': 200, 'body': json.dumps('No messages to process.')}

  creds = get_google_credentials()
  service = build('gmail', 'v1', credentials=creds)

  trashed_count = 0
  for msg_id in message_ids:
    try:
      # 1. Inspect message metadata to find the sender
      detail = (
          service.users()
          .messages()
          .get(userId='me', id=msg_id, format='metadata')
          .execute()
      )

      headers = {
          h['name']: h['value']
          for h in detail.get('payload', {}).get('headers', [])
      }
      sender_full = headers.get('From', '')
      sender = sender_full.split('<')[-1].replace('>', '').lower().strip()

      # 2. Check active_routing_rules for this sender
      rule_resp = RULES_TABLE.get_item(Key={'sender_address': sender})
      active_policy = rule_resp.get('Item', {}).get('active_policy', 'ALLOW')

      logger.info(
          f'Message ID: {msg_id} | Sender: {sender} | Active Policy:'
          f' {active_policy}'
      )

      # 3. Enforce policy
      if active_policy == 'DELETE':
        service.users().messages().trash(userId='me', id=msg_id).execute()
        logger.info(f'Successfully trashed message {msg_id} from {sender}')
        trashed_count += 1

    except Exception as e:
      logger.error(
          f'Error processing enforcement for message {msg_id}: {str(e)}'
      )

  logger.info(
      f'=== Enforcement Complete. Trashed {trashed_count} messages. ==='
  )
  return {
      'statusCode': 200,
      'body': json.dumps(f'Trashed {trashed_count} messages.'),
  }