"""Storage and feedback tests using moto, a fake AWS that runs in memory."""

import boto3
from moto import mock_aws

from reviewbot.config import Settings
from reviewbot.feedback import compute_thresholds, feedback_from_reactions, tune_thresholds
from reviewbot.job_queue import JobQueue
from reviewbot.stats import compute_stats
from reviewbot.storage import Storage


def test_feedback_from_reactions():
    assert feedback_from_reactions([{"content": "+1"}, {"content": "+1"}, {"content": "-1"}]) == ("up", 2, 1)
    assert feedback_from_reactions([{"content": "-1"}]) == ("down", 0, 1)
    assert feedback_from_reactions([{"content": "heart"}]) == ("none", 0, 0)


def test_compute_thresholds_raises_bar_for_unhelpful_category():
    comments = [{"category": "testing", "thumbsUp": 1, "thumbsDown": 1} for _ in range(2)]
    comments += [{"category": "testing", "thumbsUp": 0, "thumbsDown": 1} for _ in range(4)]
    comments += [{"category": "security", "thumbsUp": 1, "thumbsDown": 0} for _ in range(6)]
    result = compute_thresholds(comments, {}, 0.7)
    assert result["testing"] == 0.8
    assert result["security"] == 0.65


@mock_aws
def test_storage_roundtrip_and_tuning():
    settings = Settings(aws_region="ap-south-1")
    storage = Storage(settings)
    storage.create_tables_if_missing()

    storage.save_review({"reviewId": "r1", "repo": "me/x", "prNumber": 1, "riskLevel": "high",
                         "commentCount": 2, "latencyMs": 20000, "costInr": 0.5, "createdAt": "2026-10-30T10:00:00"})
    for index in range(6):
        storage.save_comment({"commentId": f"c{index}", "reviewId": "r1", "repo": "me/x", "category": "testing",
                              "confidence": 0.75, "feedback": "none", "thumbsUp": 0, "thumbsDown": 0})
        storage.update_comment_feedback(f"c{index}", "down", 0, 1)

    assert storage.get_review("r1")["costInr"] == 0.5
    assert len(storage.list_comments_for_review("r1")) == 6
    assert tune_thresholds(storage, 0.7) == 1
    assert storage.get_repo_config("me/x")["tunedThresholds"]["testing"] == 0.8

    stats = compute_stats(storage.list_reviews(), storage.list_comments(), storage.list_repo_configs())
    assert stats["totals"]["reviews"] == 1
    assert stats["totals"]["helpfulRate"] == 0.0

    storage.cache_put("k", {"a": 1})
    assert storage.cache_get("k") == {"a": 1}


@mock_aws
def test_queue_send_receive_delete():
    boto3.client("sqs", region_name="ap-south-1").create_queue(QueueName="reviewbot-jobs")
    queue = JobQueue(Settings(aws_region="ap-south-1"))
    queue.send({"type": "review_pr", "repo": "me/x"})
    messages = queue.receive(wait_seconds=0)
    assert messages[0][0]["repo"] == "me/x"
    queue.delete(messages[0][1])
