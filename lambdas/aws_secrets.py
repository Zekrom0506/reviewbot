"""Loads secrets from AWS Secrets Manager into environment variables, once
per Lambda container, so reviewbot.config.load_settings() can read them.

The secret is a JSON object like:
{
  "GITHUB_APP_ID": "123456",
  "GITHUB_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\\n...",
  "GITHUB_WEBHOOK_SECRET": "...",
  "GROQ_API_KEY": "gsk_...",
  "DATABASE_URL": "postgresql://..."     (optional, e.g. a free Neon database)
}
"""

import json
import os

import boto3

_loaded = False


def load_secrets_into_environment() -> None:
    global _loaded
    if _loaded:
        return
    secret_arn = os.environ.get("SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager")
        secret = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
        for key, value in secret.items():
            if value:
                os.environ[key] = str(value)
    _loaded = True
