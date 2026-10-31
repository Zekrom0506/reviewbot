"""All AWS resources for ReviewBot, written with the AWS CDK.

  API Gateway (HTTP API)  POST /webhook  -> webhook Lambda -> SQS queue
                          GET /dashboard, /api/stats -> dashboard Lambda
  SQS queue (+ dead-letter queue)        -> worker Lambda
  EventBridge, every 10 minutes          -> feedback Lambda
  DynamoDB tables: reviews, comments, repoconfig, cache
  Secrets Manager secret for GitHub App + Groq credentials
  CloudWatch dashboard and an alarm when jobs land in the DLQ
"""

import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
TABLE_PREFIX = "reviewbot"


class ReviewBotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------- Secrets ----------------
        secret = secretsmanager.Secret(
            self,
            "AppSecret",
            secret_name="reviewbot/app",
            description="GitHub App credentials, Groq key and optional DATABASE_URL for ReviewBot",
        )

        # ---------------- Queue ----------------
        dead_letter_queue = sqs.Queue(self, "JobsDLQ", queue_name="reviewbot-jobs-dlq",
                                      retention_period=Duration.days(14))
        queue = sqs.Queue(
            self,
            "JobsQueue",
            queue_name="reviewbot-jobs",
            visibility_timeout=Duration.seconds(360),  # must be longer than the worker timeout
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dead_letter_queue),
        )

        # ---------------- Tables ----------------
        def make_table(short_name: str, key: str, index: tuple | None = None, ttl: str | None = None):
            table = dynamodb.Table(
                self,
                f"{short_name.capitalize()}Table",
                table_name=f"{TABLE_PREFIX}-{short_name}",
                partition_key=dynamodb.Attribute(name=key, type=dynamodb.AttributeType.STRING),
                billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                removal_policy=RemovalPolicy.DESTROY,
                time_to_live_attribute=ttl,
            )
            if index:
                table.add_global_secondary_index(
                    index_name=index[0],
                    partition_key=dynamodb.Attribute(name=index[1], type=dynamodb.AttributeType.STRING),
                )
            return table

        tables = [
            make_table("reviews", "reviewId", ("repo-index", "repo")),
            make_table("comments", "commentId", ("review-index", "reviewId")),
            make_table("repoconfig", "repo"),
            make_table("cache", "cacheKey", ttl="expiresAt"),
        ]

        # ---------------- Lambda functions ----------------
        common_environment = {
            "SECRET_ARN": secret.secret_arn,
            "QUEUE_URL": queue.queue_url,
            "TABLE_PREFIX": TABLE_PREFIX,
        }

        def make_function(name: str, handler: str, timeout_seconds: int, memory_mb: int):
            function = lambda_.DockerImageFunction(
                self,
                name,
                code=lambda_.DockerImageCode.from_image_asset(
                    PROJECT_ROOT,
                    file="Dockerfile.lambda",
                    cmd=[handler],
                    exclude=["data", "infra/cdk.out", ".git", "node_modules"],
                ),
                architecture=lambda_.Architecture.ARM_64,
                timeout=Duration.seconds(timeout_seconds),
                memory_size=memory_mb,
                environment=common_environment,
                log_group=logs.LogGroup(self, f"{name}Logs", retention=logs.RetentionDays.TWO_WEEKS,
                                        removal_policy=RemovalPolicy.DESTROY),
            )
            secret.grant_read(function)
            for table in tables:
                table.grant_read_write_data(function)
            return function

        webhook_function = make_function("WebhookFunction", "lambdas.webhook_handler.handler", 10, 512)
        worker_function = make_function("WorkerFunction", "lambdas.worker_handler.handler", 300, 2048)
        feedback_function = make_function("FeedbackFunction", "lambdas.feedback_handler.handler", 120, 512)
        dashboard_function = make_function("DashboardFunction", "lambdas.dashboard_handler.handler", 15, 512)

        queue.grant_send_messages(webhook_function)
        worker_function.add_event_source(
            event_sources.SqsEventSource(queue, batch_size=1, report_batch_item_failures=True)
        )

        events.Rule(
            self,
            "FeedbackSchedule",
            schedule=events.Schedule.rate(Duration.minutes(10)),
            targets=[targets.LambdaFunction(feedback_function)],
        )

        # ---------------- API Gateway ----------------
        api = apigw.HttpApi(self, "WebhookApi", api_name="reviewbot")
        api.add_routes(
            path="/webhook",
            methods=[apigw.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("WebhookIntegration", webhook_function),
        )
        dashboard_integration = integrations.HttpLambdaIntegration("DashboardIntegration", dashboard_function)
        for path in ("/dashboard", "/api/stats"):
            api.add_routes(path=path, methods=[apigw.HttpMethod.GET], integration=dashboard_integration)

        # ---------------- Monitoring ----------------
        dlq_alarm = cloudwatch.Alarm(
            self,
            "DeadLetterAlarm",
            metric=dead_letter_queue.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            alarm_description="A review job failed 3 times and is in the dead-letter queue",
        )

        def review_metric(name: str, statistic: str) -> cloudwatch.Metric:
            return cloudwatch.Metric(namespace="ReviewBot", metric_name=name, statistic=statistic,
                                     period=Duration.hours(1))

        dashboard = cloudwatch.Dashboard(self, "Dashboard", dashboard_name="ReviewBot")
        dashboard.add_widgets(
            cloudwatch.GraphWidget(title="Reviews completed", left=[review_metric("ReviewsCompleted", "Sum")]),
            cloudwatch.GraphWidget(title="Review latency (ms)", left=[review_metric("ReviewLatencyMs", "Average"),
                                                                     review_metric("ReviewLatencyMs", "p95")]),
            cloudwatch.GraphWidget(title="Cost per review (INR)", left=[review_metric("ReviewCostInr", "Average")]),
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(title="Queue depth", left=[queue.metric_approximate_number_of_messages_visible()]),
            cloudwatch.GraphWidget(title="Worker errors", left=[worker_function.metric_errors()]),
            cloudwatch.AlarmWidget(title="Dead-letter queue", alarm=dlq_alarm),
        )

        CfnOutput(self, "WebhookUrl", value=f"{api.api_endpoint}/webhook")
        CfnOutput(self, "DashboardUrl", value=f"{api.api_endpoint}/dashboard")
        CfnOutput(self, "SecretName", value=secret.secret_name)
