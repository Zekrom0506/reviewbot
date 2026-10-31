"""The local worker: an endless loop that takes jobs from the queue.

On AWS this file is not used; SQS triggers lambdas/worker_handler.py instead.
Run locally with:  python -m reviewbot.worker
"""

import logging
import time

from reviewbot.config import load_settings
from reviewbot.job_queue import JobQueue
from reviewbot.jobs import JobRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reviewbot.worker")

FEEDBACK_SYNC_SECONDS = 5 * 60


def wait_for_github_app():
    """Before the one-click setup is done there are no App credentials.
    Wait patiently instead of crashing."""
    while True:
        settings = load_settings()
        if settings.github_app_id and settings.github_private_key:
            return settings
        logger.info("Waiting for GitHub App setup... open %s/setup", settings.public_url)
        time.sleep(15)


def main():
    settings = wait_for_github_app()
    queue = JobQueue(settings)
    runner = JobRunner(settings)
    runner.storage.create_tables_if_missing()
    logger.info("Worker started, waiting for jobs")

    last_feedback_sync = 0.0
    while True:
        if time.time() - last_feedback_sync > FEEDBACK_SYNC_SECONDS:
            try:
                runner.run({"type": "sync_feedback"})
            except Exception:
                logger.exception("Feedback sync failed")
            last_feedback_sync = time.time()

        for job, receipt_handle in queue.receive(max_messages=1, wait_seconds=10):
            logger.info("Processing job: %s", job)
            try:
                result = runner.run(job)
                logger.info("Job finished: %s", result)
                queue.delete(receipt_handle)
            except Exception:
                # Not deleting the message means SQS will retry it later.
                # After 3 failed attempts it moves to the dead-letter queue.
                logger.exception("Job failed, it will be retried")


if __name__ == "__main__":
    main()
