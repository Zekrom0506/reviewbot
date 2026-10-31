"""Serves the dashboard page and its stats API from Lambda (GET /dashboard,
GET /api/stats), so the AWS deployment has the same dashboard as local."""

import json
from pathlib import Path

from lambdas.aws_secrets import load_secrets_into_environment
from reviewbot.config import load_settings
from reviewbot.stats import compute_stats
from reviewbot.storage import Storage

DASHBOARD_FILE = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


def handler(event, context):
    load_secrets_into_environment()
    path = event.get("rawPath", "/")
    if path.startswith("/api/stats"):
        storage = Storage(load_settings())
        stats = compute_stats(storage.list_reviews(), storage.list_comments(), storage.list_repo_configs())
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(stats)}
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": DASHBOARD_FILE.read_text()}
