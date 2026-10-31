"""SQS -> this Lambda. Runs one review (or indexing) job per message.

Returning a message id in "batchItemFailures" tells SQS to retry only that
message; after 3 failures SQS moves it to the dead-letter queue.
"""

import json
import logging

from lambdas.aws_secrets import load_secrets_into_environment
from reviewbot.config import load_settings
from reviewbot.jobs import JobRunner

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_runner = None


def handler(event, context):
    global _runner
    load_secrets_into_environment()
    if _runner is None:
        _runner = JobRunner(load_settings())

    failures = []
    for record in event.get("Records", []):
        try:
            job = json.loads(record["body"])
            result = _runner.run(job)
            logger.info("Job %s finished: %s", job.get("type"), result)
        except Exception:
            logger.exception("Job failed")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
