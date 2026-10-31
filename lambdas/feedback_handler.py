"""Runs every 10 minutes (EventBridge schedule): reads 👍/👎 reactions and
re-tunes confidence thresholds."""

import logging

from lambdas.aws_secrets import load_secrets_into_environment
from reviewbot.config import load_settings
from reviewbot.feedback import sync_feedback
from reviewbot.storage import Storage

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    load_secrets_into_environment()
    settings = load_settings()
    result = sync_feedback(settings, Storage(settings))
    logger.info("Feedback sync result: %s", result)
    return result
