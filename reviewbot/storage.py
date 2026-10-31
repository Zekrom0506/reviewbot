"""DynamoDB storage for reviews, comments, repo settings and a small cache.

Locally this talks to "DynamoDB Local" (Amazon's free offline version) in
Docker. On AWS it talks to real DynamoDB. Same code, different endpoint.

Tables:
  <prefix>-reviews     reviewId (PK)  repo, prNumber, riskLevel, commentCount,
                                       latencyMs, costInr, model, createdAt ...
  <prefix>-comments    commentId (PK) reviewId, repo, file, line, category,
                                       confidence, feedback, githubCommentId ...
  <prefix>-repoconfig  repo (PK)      rules, ignoredPaths, strictness,
                                       tunedThresholds
  <prefix>-cache       cacheKey (PK)  value, expiresAt
"""

import json
import logging
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from reviewbot.config import Settings

logger = logging.getLogger(__name__)


def _to_dynamo(value):
    """DynamoDB does not accept Python floats, only Decimal."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _to_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(item) for item in value]
    return value


def _from_dynamo(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: _from_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(item) for item in value]
    return value


TABLE_DEFINITIONS = {
    "reviews": {"key": "reviewId", "indexes": [("repo-index", "repo")]},
    "comments": {"key": "commentId", "indexes": [("review-index", "reviewId")]},
    "repoconfig": {"key": "repo", "indexes": []},
    "cache": {"key": "cacheKey", "indexes": []},
}


class Storage:
    def __init__(self, settings: Settings):
        resource_args = {"region_name": settings.aws_region}
        if settings.dynamodb_endpoint_url:
            resource_args["endpoint_url"] = settings.dynamodb_endpoint_url
        self.dynamodb = boto3.resource("dynamodb", **resource_args)
        self.prefix = settings.table_prefix
        self.reviews = self.dynamodb.Table(f"{self.prefix}-reviews")
        self.comments = self.dynamodb.Table(f"{self.prefix}-comments")
        self.repo_config = self.dynamodb.Table(f"{self.prefix}-repoconfig")
        self.cache = self.dynamodb.Table(f"{self.prefix}-cache")

    # ------------------------------------------------------------------
    # Setup (used locally; on AWS the CDK stack creates the tables)
    # ------------------------------------------------------------------
    def create_tables_if_missing(self) -> None:
        existing = [table.name for table in self.dynamodb.tables.all()]
        for short_name, definition in TABLE_DEFINITIONS.items():
            name = f"{self.prefix}-{short_name}"
            if name in existing:
                continue
            attributes = [{"AttributeName": definition["key"], "AttributeType": "S"}]
            indexes = []
            for index_name, index_key in definition["indexes"]:
                attributes.append({"AttributeName": index_key, "AttributeType": "S"})
                indexes.append(
                    {
                        "IndexName": index_name,
                        "KeySchema": [{"AttributeName": index_key, "KeyType": "HASH"}],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                )
            create_args = {
                "TableName": name,
                "KeySchema": [{"AttributeName": definition["key"], "KeyType": "HASH"}],
                "AttributeDefinitions": attributes,
                "BillingMode": "PAY_PER_REQUEST",
            }
            if indexes:
                create_args["GlobalSecondaryIndexes"] = indexes
            self.dynamodb.create_table(**create_args)
            logger.info("Created table %s", name)

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------
    def save_review(self, review: dict) -> None:
        self.reviews.put_item(Item=_to_dynamo(review))

    def get_review(self, review_id: str) -> dict | None:
        item = self.reviews.get_item(Key={"reviewId": review_id}).get("Item")
        return _from_dynamo(item) if item else None

    def list_reviews(self) -> list:
        return [_from_dynamo(item) for item in self._scan_all(self.reviews)]

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------
    def save_comment(self, comment: dict) -> None:
        self.comments.put_item(Item=_to_dynamo(comment))

    def list_comments(self) -> list:
        return [_from_dynamo(item) for item in self._scan_all(self.comments)]

    def list_comments_for_review(self, review_id: str) -> list:
        response = self.comments.query(IndexName="review-index", KeyConditionExpression=Key("reviewId").eq(review_id))
        return [_from_dynamo(item) for item in response.get("Items", [])]

    def list_comments_for_repo(self, repo: str) -> list:
        items = self._scan_all(self.comments, Attr("repo").eq(repo))
        return [_from_dynamo(item) for item in items]

    def update_comment_feedback(self, comment_id: str, feedback: str, up: int, down: int) -> None:
        self.comments.update_item(
            Key={"commentId": comment_id},
            UpdateExpression="SET feedback = :f, thumbsUp = :u, thumbsDown = :d, feedbackCheckedAt = :t",
            ExpressionAttributeValues={":f": feedback, ":u": up, ":d": down, ":t": int(time.time())},
        )

    # ------------------------------------------------------------------
    # Repo config
    # ------------------------------------------------------------------
    def get_repo_config(self, repo: str) -> dict:
        item = self.repo_config.get_item(Key={"repo": repo}).get("Item")
        return _from_dynamo(item) if item else {"repo": repo}

    def save_repo_config(self, config: dict) -> None:
        self.repo_config.put_item(Item=_to_dynamo(config))

    def list_repo_configs(self) -> list:
        return [_from_dynamo(item) for item in self._scan_all(self.repo_config)]

    # ------------------------------------------------------------------
    # Cache: used to skip re-analysing files that did not change
    # ------------------------------------------------------------------
    def cache_get(self, key: str):
        try:
            item = self.cache.get_item(Key={"cacheKey": key}).get("Item")
        except ClientError:
            return None
        if not item or int(item.get("expiresAt", 0)) < time.time():
            return None
        return json.loads(item["value"])

    def cache_put(self, key: str, value, ttl_seconds: int = 7 * 24 * 3600) -> None:
        item = {"cacheKey": key, "value": json.dumps(value), "expiresAt": int(time.time()) + ttl_seconds}
        try:
            self.cache.put_item(Item=item)
        except ClientError as error:
            logger.warning("Cache write failed: %s", error)

    # ------------------------------------------------------------------
    @staticmethod
    def _scan_all(table, filter_expression=None) -> list:
        items = []
        scan_args = {}
        if filter_expression is not None:
            scan_args["FilterExpression"] = filter_expression
        while True:
            response = table.scan(**scan_args)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            scan_args["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return items
