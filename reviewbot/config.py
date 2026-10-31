"""All settings for the bot live here.

Every value is read from an environment variable so the same code can run
on your laptop (Docker Compose) or on AWS Lambda without changes.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _get_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


@dataclass
class Settings:
    # --- GitHub App ---
    github_app_id: str = ""
    github_private_key: str = ""
    github_webhook_secret: str = ""
    github_api_url: str = "https://api.github.com"

    # --- LLM (Groq, OpenAI-compatible API) ---
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    small_model: str = "openai/gpt-oss-20b"
    large_model: str = "openai/gpt-oss-120b"
    # Price per 1 million tokens in US dollars: (input, output)
    small_model_price: tuple = (0.075, 0.30)
    large_model_price: tuple = (0.15, 0.60)
    usd_to_inr: float = 88.0
    # Diffs with fewer changed lines than this use the small model
    small_diff_line_limit: int = 150

    # --- Review behaviour ---
    max_comments_per_pr: int = 5
    min_confidence: float = 0.7
    max_chunk_lines: int = 400

    # --- AWS (or local stand-ins) ---
    aws_region: str = "ap-south-1"
    sqs_endpoint_url: str = ""
    dynamodb_endpoint_url: str = ""
    queue_url: str = ""
    queue_name: str = "reviewbot-jobs"
    table_prefix: str = "reviewbot"

    # --- Retrieval ---
    database_url: str = ""
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    retrieval_top_k: int = 4

    # --- Misc ---
    public_url: str = "http://localhost:8000"
    smee_url: str = ""
    secrets_file: str = "/data/secrets/github_app.json"
    extra: dict = field(default_factory=dict)


def load_settings() -> Settings:
    settings = Settings(
        github_app_id=os.environ.get("GITHUB_APP_ID", ""),
        github_private_key=os.environ.get("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n"),
        github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
        github_api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        llm_api_key=os.environ.get("GROQ_API_KEY", os.environ.get("LLM_API_KEY", "")),
        llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        small_model=os.environ.get("SMALL_MODEL", "openai/gpt-oss-20b"),
        large_model=os.environ.get("LARGE_MODEL", "openai/gpt-oss-120b"),
        usd_to_inr=_get_float("USD_TO_INR", 88.0),
        small_diff_line_limit=_get_int("SMALL_DIFF_LINE_LIMIT", 150),
        max_comments_per_pr=_get_int("MAX_COMMENTS_PER_PR", 5),
        min_confidence=_get_float("MIN_CONFIDENCE", 0.7),
        max_chunk_lines=_get_int("MAX_CHUNK_LINES", 400),
        aws_region=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")),
        sqs_endpoint_url=os.environ.get("SQS_ENDPOINT_URL", ""),
        dynamodb_endpoint_url=os.environ.get("DYNAMODB_ENDPOINT_URL", ""),
        queue_url=os.environ.get("QUEUE_URL", ""),
        queue_name=os.environ.get("QUEUE_NAME", "reviewbot-jobs"),
        table_prefix=os.environ.get("TABLE_PREFIX", "reviewbot"),
        database_url=os.environ.get("DATABASE_URL", ""),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        retrieval_top_k=_get_int("RETRIEVAL_TOP_K", 4),
        public_url=os.environ.get("PUBLIC_URL", "http://localhost:8000"),
        smee_url=os.environ.get("SMEE_URL", ""),
        secrets_file=os.environ.get("SECRETS_FILE", "/data/secrets/github_app.json"),
    )

    # The one-click setup page saves GitHub App credentials to a JSON file.
    # If environment variables are empty we fall back to that file.
    secrets_path = Path(settings.secrets_file)
    if secrets_path.exists():
        saved = json.loads(secrets_path.read_text())
        if not settings.github_app_id:
            settings.github_app_id = str(saved.get("app_id", ""))
        if not settings.github_private_key:
            settings.github_private_key = saved.get("private_key", "")
        if not settings.github_webhook_secret:
            settings.github_webhook_secret = saved.get("webhook_secret", "")
        settings.extra["app_slug"] = saved.get("slug", "")
        settings.extra["app_html_url"] = saved.get("html_url", "")

    return settings


def debug_enabled() -> bool:
    return _get_bool("DEBUG", False)
