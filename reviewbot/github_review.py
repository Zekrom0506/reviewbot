"""Runs the pipeline on a live GitHub pull request and posts the result."""

import logging
import time
import uuid
from datetime import datetime, timezone

from reviewbot.config import Settings
from reviewbot.formatting import to_github_comment
from reviewbot.github_client import GitHubClient
from reviewbot.metrics import publish_review_metrics
from reviewbot.pipeline import ReviewInput, ReviewPipeline
from reviewbot.repo_config import parse_repo_config
from reviewbot.retrieval.indexer import index_repository

logger = logging.getLogger(__name__)

MAX_FILES = 40
MAX_FILE_BYTES = 300_000


def review_pull_request(settings: Settings, job: dict, llm, store, embedder, storage) -> dict:
    started = time.time()
    repo = job["repo"]
    number = int(job["pr_number"])
    github = GitHubClient(settings, int(job["installation_id"]))

    pr = github.get_pull_request(repo, number)
    if pr.get("draft"):
        logger.info("Skipping draft PR %s#%d", repo, number)
        return {"skipped": "draft"}
    head_sha = pr["head"]["sha"]
    base_ref = pr["base"]["ref"]

    # Make sure the repo is indexed at least once before the first review.
    if store.chunk_count(repo) == 0:
        try:
            base_sha = github.get_branch_sha(repo, base_ref) or base_ref
            index_repository(github, store, embedder, repo, base_sha)
        except Exception as error:
            logger.warning("Initial indexing failed: %s", error)

    diff_text = github.get_pull_request_diff(repo, number)
    pr_files = github.list_pull_request_files(repo, number)

    files = {}
    file_shas = {}
    for item in pr_files[:MAX_FILES]:
        if item.get("status") == "removed" or item.get("changes", 0) == 0 and item.get("status") != "added":
            continue
        try:
            content = github.get_blob(repo, item["sha"])
        except Exception as error:
            logger.warning("Could not fetch %s: %s", item["filename"], error)
            continue
        if len(content) > MAX_FILE_BYTES:
            continue
        files[item["filename"]] = content
        file_shas[item["filename"]] = item["sha"]

    config_text = github.get_file_content(repo, ".reviewbot.yml", base_ref)
    config = parse_repo_config(config_text, storage.get_repo_config(repo))

    pipeline = ReviewPipeline(settings, llm, store, embedder, storage)
    result = pipeline.run(
        ReviewInput(
            repo=repo,
            title=pr.get("title", ""),
            body=pr.get("body") or "",
            diff_text=diff_text,
            files=files,
            file_shas=file_shas,
            config=config,
        )
    )

    github_comments = [to_github_comment(comment) for comment in result.comments]
    posted = github.create_review(repo, number, head_sha, result.summary_markdown, github_comments)
    github.set_risk_label(repo, number, result.risk_level)

    # Match our comments to the IDs GitHub assigned so we can read reactions later.
    github_ids = {}
    try:
        for posted_comment in github.list_review_comments(repo, number, posted["id"]):
            line = posted_comment.get("line") or posted_comment.get("original_line")
            github_ids[(posted_comment["path"], line)] = posted_comment["id"]
    except Exception as error:
        logger.warning("Could not list posted comments: %s", error)

    total_latency_ms = int((time.time() - started) * 1000)
    review_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    storage.save_review(
        {
            "reviewId": review_id,
            "repo": repo,
            "prNumber": number,
            "headSha": head_sha,
            "riskLevel": result.risk_level,
            "riskReasons": result.risk_reasons,
            "commentCount": len(result.comments),
            "staticFindings": len(result.findings),
            "latencyMs": total_latency_ms,
            "pipelineMs": result.latency_ms,
            "costInr": result.cost_inr,
            "inputTokens": result.input_tokens,
            "outputTokens": result.output_tokens,
            "llmCalls": result.llm_calls,
            "cacheHits": result.cache_hits,
            "changedLines": result.changed_lines,
            "model": result.model,
            "githubReviewId": posted.get("id"),
            "createdAt": now,
        }
    )
    for comment in result.comments:
        storage.save_comment(
            {
                "commentId": str(uuid.uuid4()),
                "reviewId": review_id,
                "repo": repo,
                "prNumber": number,
                "file": comment["file"],
                "line": comment["line"],
                "category": comment["category"],
                "severity": comment["severity"],
                "confidence": comment["confidence"],
                "source": comment["source"],
                "title": comment["title"],
                "githubCommentId": github_ids.get((comment["file"], comment["line"]), 0),
                "feedback": "none",
                "thumbsUp": 0,
                "thumbsDown": 0,
                "createdAt": now,
            }
        )

    publish_review_metrics(total_latency_ms, result.cost_inr, len(result.comments), result.risk_level)
    logger.info(
        "Reviewed %s#%d: risk=%s comments=%d cost=₹%.3f latency=%.1fs",
        repo, number, result.risk_level, len(result.comments), result.cost_inr, total_latency_ms / 1000,
    )
    return {"reviewId": review_id, "comments": len(result.comments), "risk": result.risk_level}


def index_repo_job(settings: Settings, job: dict, store, embedder) -> dict:
    github = GitHubClient(settings, int(job["installation_id"]))
    ref = job["ref"]
    if ref == "HEAD":
        default_branch = github.get_repo(job["repo"]).get("default_branch", "main")
        ref = github.get_branch_sha(job["repo"], default_branch)
        if ref is None:
            return {"skipped": "empty repository"}
    return index_repository(github, store, embedder, job["repo"], ref)
