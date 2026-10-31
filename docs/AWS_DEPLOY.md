# Deploying ReviewBot to AWS

Everything runs locally without AWS. Do this once your AWS account works.

## What gets created

| Resource | Purpose |
|---|---|
| API Gateway HTTP API | `POST /webhook` for GitHub, `GET /dashboard` and `/api/stats` |
| Lambda `WebhookFunction` | verifies the signature and sends jobs to SQS (10 s timeout) |
| SQS `reviewbot-jobs` + `reviewbot-jobs-dlq` | job queue; a job that fails 3 times moves to the DLQ |
| Lambda `WorkerFunction` | runs reviews and indexing (5 min timeout, 2 GB, arm64) |
| Lambda `FeedbackFunction` | reads 👍/👎 every 10 minutes and tunes thresholds |
| Lambda `DashboardFunction` | serves the same dashboard as the local version |
| DynamoDB `reviewbot-*` tables | reviews, comments, repo config, cache (with TTL) |
| Secrets Manager `reviewbot/app` | GitHub App + Groq credentials |
| CloudWatch dashboard + alarm | latency, cost, queue depth, worker errors, DLQ alarm |

All Lambdas share one container image (`Dockerfile.lambda`).

## Steps

Run these on your Mac.

```bash
# 1. Tools (once)
brew install awscli node
npm install -g aws-cdk
aws configure                 # access key, secret, region ap-south-1

# 2. Install CDK's Python library
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. One-time CDK bootstrap for your account/region
cdk bootstrap

# 4. Deploy (Docker must be running; it builds the Lambda image)
cdk deploy
```

The deploy prints `WebhookUrl`, `DashboardUrl` and `SecretName`.

## Fill in the secret

Open **Secrets Manager → reviewbot/app → Retrieve secret value → Edit → Plaintext** and paste:

```json
{
  "GITHUB_APP_ID": "<from data/secrets/github_app.json: app_id>",
  "GITHUB_PRIVATE_KEY": "<private_key, keep the \n line breaks>",
  "GITHUB_WEBHOOK_SECRET": "<webhook_secret>",
  "GROQ_API_KEY": "<your Groq key>",
  "DATABASE_URL": "<optional: Postgres with pgvector, e.g. a free Neon database>"
}
```

Without `DATABASE_URL`, the worker uses an in-memory index that is rebuilt when a Lambda container starts. That works, but the first review after a cold start is slower. A free Neon or Supabase Postgres (both support pgvector) fixes that.

## Point GitHub at AWS

GitHub → Settings → Developer settings → GitHub Apps → your app → **Webhook URL** = the `WebhookUrl` output. Save. You can stop the local Docker stack now.

## Automatic deploys from GitHub Actions (optional)

1. In IAM, create an OIDC identity provider for `token.actions.githubusercontent.com`.
2. Create a role that this repo's workflows can assume, with permissions to deploy CDK stacks.
3. Add the role ARN as the repository secret `AWS_ROLE_ARN`.

From then on, every push to `main` that passes tests runs `cdk deploy`.

## Cost

Within the free tier, small usage costs close to nothing. Lambda, SQS, DynamoDB on-demand and API Gateway are all pay-per-request. Secrets Manager costs about $0.40/month per secret. Groq's free tier covers the LLM.

## Tear down

```bash
cd infra && cdk destroy
```
