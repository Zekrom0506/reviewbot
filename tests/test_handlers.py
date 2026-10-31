"""Tests for the local web server and the AWS Lambda webhook handler."""

import json

import boto3
from fastapi.testclient import TestClient
from moto import mock_aws

from reviewbot.signature import compute_signature

PR_EVENT = {
    "action": "opened",
    "installation": {"id": 9},
    "repository": {"full_name": "me/shop", "default_branch": "main"},
    "pull_request": {"number": 4, "draft": False, "head": {"sha": "abc"}},
}


def setup_queue(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    sqs = boto3.client("sqs", region_name="ap-south-1")
    url = sqs.create_queue(QueueName="reviewbot-jobs")["QueueUrl"]
    monkeypatch.setenv("QUEUE_URL", url)
    return sqs, url


@mock_aws
def test_lambda_webhook_queues_job(monkeypatch):
    sqs, url = setup_queue(monkeypatch)
    import lambdas.webhook_handler as webhook_handler

    webhook_handler._queue = None
    body = json.dumps(PR_EVENT)
    event = {
        "headers": {"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": compute_signature("s3cret", body.encode())},
        "body": body,
        "isBase64Encoded": False,
    }
    response = webhook_handler.handler(event, None)
    assert response["statusCode"] == 200
    messages = sqs.receive_message(QueueUrl=url).get("Messages", [])
    assert json.loads(messages[0]["Body"])["pr_number"] == 4

    event["headers"]["X-Hub-Signature-256"] = "sha256=bad"
    assert webhook_handler.handler(event, None)["statusCode"] == 401


@mock_aws
def test_server_webhook_and_stats(monkeypatch):
    sqs, url = setup_queue(monkeypatch)
    monkeypatch.setenv("SMEE_URL", "https://smee.io/test")
    import reviewbot.server as server

    server._queue = None
    server._storage = None
    client = TestClient(server.app)

    body = json.dumps(PR_EVENT).encode()
    headers = {"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": compute_signature("s3cret", body)}
    response = client.post("/webhook", content=body, headers=headers)
    assert response.json() == {"queued": 1}
    assert client.post("/webhook", content=body, headers={"X-GitHub-Event": "pull_request"}).status_code == 401

    stats = client.get("/api/stats").json()
    assert stats["totals"]["reviews"] == 0
    assert "ReviewBot" in client.get("/dashboard").text
    assert "Create your ReviewBot GitHub App" in client.get("/setup").text
