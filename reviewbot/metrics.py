"""Publishes review metrics to CloudWatch when running on AWS Lambda.

It uses the "Embedded Metric Format": printing a specially shaped JSON line
to the logs is enough for CloudWatch to turn it into metrics. No extra API
calls, no extra cost. Locally (not on Lambda) this does nothing.
"""

import json
import os
import time

NAMESPACE = "ReviewBot"


def publish_review_metrics(latency_ms: int, cost_inr: float, comment_count: int, risk_level: str) -> None:
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [[]],
                    "Metrics": [
                        {"Name": "ReviewLatencyMs", "Unit": "Milliseconds"},
                        {"Name": "ReviewCostInr", "Unit": "None"},
                        {"Name": "CommentsPosted", "Unit": "Count"},
                        {"Name": "ReviewsCompleted", "Unit": "Count"},
                    ],
                }
            ],
        },
        "ReviewLatencyMs": latency_ms,
        "ReviewCostInr": cost_inr,
        "CommentsPosted": comment_count,
        "ReviewsCompleted": 1,
        "riskLevel": risk_level,
    }
    print(json.dumps(record))
