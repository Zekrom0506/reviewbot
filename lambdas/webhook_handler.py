"""API Gateway -> this Lambda -> SQS.

Verifies the GitHub signature and queues jobs. It does no heavy work, so it
answers GitHub in well under a second.
"""

import base64
import json
import logging

from lambdas.aws_secrets import load_secrets_into_environment
from reviewbot.config import load_settings
from reviewbot.job_queue import JobQueue
from reviewbot.signature import verify_signature
from reviewbot.webhooks import jobs_from_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_queue = None


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def handler(event, context):
    global _queue
    load_secrets_into_environment()
    settings = load_settings()

    # API Gateway lowercases header names in HTTP APIs
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    body = event.get("body") or ""
    body_bytes = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")

    if not verify_signature(settings.github_webhook_secret, body_bytes, headers.get("x-hub-signature-256", "")):
        return _response(401, {"error": "invalid signature"})

    jobs = jobs_from_event(headers.get("x-github-event", ""), json.loads(body_bytes))
    if jobs:
        if _queue is None:
            _queue = JobQueue(settings)
        for job in jobs:
            _queue.send(job)
    return _response(200, {"queued": len(jobs)})
