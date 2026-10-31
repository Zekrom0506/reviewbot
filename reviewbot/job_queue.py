"""A thin wrapper around Amazon SQS.

Locally we run ElasticMQ, a free SQS-compatible server, so the exact same
boto3 code works on your laptop and on AWS. Only the endpoint URL changes.

Why a queue at all? GitHub expects the webhook to answer within 10 seconds.
A review takes ~20-30 seconds, so the webhook just drops a job on the queue
and replies immediately. Workers pick jobs up at their own pace, and bursts
of PRs simply wait in line.
"""

import json
import logging

import boto3

from reviewbot.config import Settings

logger = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, settings: Settings):
        client_args = {"region_name": settings.aws_region}
        if settings.sqs_endpoint_url:
            client_args["endpoint_url"] = settings.sqs_endpoint_url
        self.client = boto3.client("sqs", **client_args)
        self.queue_url = settings.queue_url
        if not self.queue_url:
            response = self.client.get_queue_url(QueueName=settings.queue_name)
            self.queue_url = response["QueueUrl"]

    def send(self, job: dict) -> None:
        self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps(job))
        logger.info("Queued job type=%s", job.get("type"))

    def receive(self, max_messages: int = 1, wait_seconds: int = 10) -> list:
        """Long-poll the queue. Returns a list of (job, receipt_handle)."""
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        results = []
        for message in response.get("Messages", []):
            job = json.loads(message["Body"])
            results.append((job, message["ReceiptHandle"]))
        return results

    def delete(self, receipt_handle: str) -> None:
        """Remove a job after it finished. Jobs that are never deleted come
        back after the visibility timeout and, after 3 failures, move to the
        dead-letter queue (DLQ) for inspection."""
        self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
