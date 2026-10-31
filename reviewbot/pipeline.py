"""The heart of the bot: turns a diff into a finished review.

This module does not talk to GitHub, which is why the evaluation script can
run it on historical PRs offline. github_review.py wraps it for live PRs.

Steps:
  1. parse the diff and drop ignored files
  2. static analysis (ruff, semgrep, secret scan) - cached per file version
  3. rule-based risk estimate
  4. retrieve related code from the index
  5. LLM review per chunk - cached per chunk, model picked by size/risk
  6. filter, merge and cap comments
  7. build the summary
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from reviewbot.analysis import run_static_analysis
from reviewbot.config import Settings
from reviewbot.diff_parser import chunk_files, parse_diff
from reviewbot.filtering import filter_comments, findings_to_comments
from reviewbot.formatting import format_summary
from reviewbot.llm import choose_model
from reviewbot.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from reviewbot.repo_config import RepoConfig
from reviewbot.retrieval.context import build_context
from reviewbot.risk import RISK_ORDER, assess_risk, max_risk

logger = logging.getLogger(__name__)
STATIC_ANALYSIS_VERSION = "sa1"


@dataclass
class ReviewInput:
    repo: str
    title: str
    body: str
    diff_text: str
    files: dict  # {path: full new content}
    file_shas: dict = field(default_factory=dict)  # {path: git blob sha}, used for caching
    config: RepoConfig = field(default_factory=RepoConfig)


@dataclass
class ReviewResult:
    summary_markdown: str
    summary_text: str
    risk_level: str
    risk_reasons: list
    comments: list
    suggested_tests: list
    findings: list
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_inr: float = 0.0
    latency_ms: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    changed_lines: int = 0
    skipped_reason: str = ""


class ReviewPipeline:
    def __init__(self, settings: Settings, llm, store, embedder, storage=None):
        self.settings = settings
        self.llm = llm
        self.store = store
        self.embedder = embedder
        self.storage = storage  # optional, used only for caching

    # ------------------------------------------------------------------
    def run(self, review_input: ReviewInput) -> ReviewResult:
        started = time.time()
        config = review_input.config

        # 1. Parse the diff
        file_diffs = []
        for file_diff in parse_diff(review_input.diff_text):
            if file_diff.is_binary or file_diff.status == "removed":
                continue
            if config.is_ignored(file_diff.path):
                continue
            if not file_diff.hunks:
                continue
            file_diffs.append(file_diff)

        if not file_diffs:
            return self._empty_result("No reviewable changes (only ignored, binary or deleted files).", started)

        added_lines = {file_diff.path: file_diff.added_line_numbers() for file_diff in file_diffs}
        commentable = {file_diff.path: file_diff.commentable_line_numbers() for file_diff in file_diffs}
        total_changed = sum(file_diff.changed_line_count() for file_diff in file_diffs)

        # 2. Static analysis
        findings = self._static_analysis(review_input, added_lines)

        # 3. Rule-based risk
        heuristic_level, heuristic_reasons = assess_risk(file_diffs, findings)

        # 4. Retrieval
        try:
            context = build_context(self.store, self.embedder, review_input.repo, file_diffs,
                                    self.settings.retrieval_top_k)
        except Exception as error:
            logger.warning("Retrieval failed, continuing without context: %s", error)
            context = {"text": "", "untested_functions": []}

        # 5. LLM review, one call per chunk
        model = choose_model(self.settings, total_changed, heuristic_level)
        chunks = chunk_files(file_diffs, self.settings.max_chunk_lines)
        summaries = []
        llm_risk = "low"
        llm_reasons = []
        raw_comments = []
        suggested_tests = []
        totals = {"input": 0, "output": 0, "cost": 0.0, "calls": 0, "hits": 0}

        for chunk in chunks:
            chunk_paths = {file_diff.path for file_diff in chunk}
            diff_text = "\n\n".join(file_diff.to_text() for file_diff in chunk)
            chunk_findings = [item for item in findings if item["file"] in chunk_paths]
            prompt = build_user_prompt(
                repo=review_input.repo,
                pr_title=review_input.title,
                pr_body=review_input.body,
                diff_text=diff_text,
                context_text=context["text"],
                findings=chunk_findings,
                rules=config.rules,
                untested_functions=[item for item in context["untested_functions"] if item["file"] in chunk_paths],
                heuristic_reasons=heuristic_reasons,
            )
            data = self._call_llm(prompt, model, totals)
            if data is None:
                continue
            if data.get("summary"):
                summaries.append(str(data["summary"]))
            level = str(data.get("risk_level", "low")).lower()
            if level in RISK_ORDER:
                llm_risk = max_risk(llm_risk, level)
            llm_reasons.extend(str(reason) for reason in data.get("risk_reasons", []) or [])
            for comment in data.get("comments", []) or []:
                if isinstance(comment, dict):
                    comment["source"] = "llm"
                    raw_comments.append(comment)
            for test in data.get("suggested_tests", []) or []:
                if isinstance(test, dict) and test.get("cases"):
                    suggested_tests.append(test)

        # 6. Filter
        raw_comments.extend(findings_to_comments(findings))
        default_confidence = self.settings.min_confidence
        comments = filter_comments(
            raw_comments,
            commentable,
            threshold_for=lambda category: config.threshold_for(category, default_confidence),
            max_comments=min(config.max_comments, self.settings.max_comments_per_pr),
        )

        # 7. Summary
        risk_level = max_risk(heuristic_level, llm_risk)
        reasons = []
        for reason in heuristic_reasons + llm_reasons:
            if reason and reason.lower() not in [existing.lower() for existing in reasons]:
                reasons.append(reason)
        reasons = reasons[:5]

        summary_text = " ".join(summaries) if summaries else "Automated summary unavailable (LLM call failed)."
        latency_ms = int((time.time() - started) * 1000)
        summary_markdown = format_summary(
            summary=summary_text,
            risk_level=risk_level,
            risk_reasons=reasons,
            suggested_tests=suggested_tests,
            comment_count=len(comments),
            model=model,
            latency_ms=latency_ms,
            static_count=len(findings),
        )
        return ReviewResult(
            summary_markdown=summary_markdown,
            summary_text=summary_text,
            risk_level=risk_level,
            risk_reasons=reasons,
            comments=comments,
            suggested_tests=suggested_tests,
            findings=findings,
            model=model,
            input_tokens=totals["input"],
            output_tokens=totals["output"],
            cost_inr=round(totals["cost"], 4),
            latency_ms=latency_ms,
            llm_calls=totals["calls"],
            cache_hits=totals["hits"],
            changed_lines=total_changed,
        )

    # ------------------------------------------------------------------
    def _static_analysis(self, review_input: ReviewInput, added_lines: dict) -> list:
        """Analyse each file once per version. On a PR update, files whose
        blob SHA did not change are read from the cache."""
        all_findings = []
        to_analyse = {}
        for path in added_lines:
            content = review_input.files.get(path)
            if content is None:
                continue
            blob_sha = review_input.file_shas.get(path)
            cache_key = f"static:{STATIC_ANALYSIS_VERSION}:{review_input.repo}:{path}:{blob_sha}"
            cached = self.storage.cache_get(cache_key) if (self.storage and blob_sha) else None
            if cached is not None:
                all_findings.extend(cached)
            else:
                to_analyse[path] = content

        if to_analyse:
            fresh = [finding.to_dict() for finding in run_static_analysis(to_analyse, None)]
            all_findings.extend(fresh)
            if self.storage:
                for path in to_analyse:
                    blob_sha = review_input.file_shas.get(path)
                    if blob_sha:
                        cache_key = f"static:{STATIC_ANALYSIS_VERSION}:{review_input.repo}:{path}:{blob_sha}"
                        self.storage.cache_put(cache_key, [item for item in fresh if item["file"] == path])

        return [item for item in all_findings if item["line"] in added_lines.get(item["file"], set())]

    def _call_llm(self, prompt: str, model: str, totals: dict):
        cache_key = "llm:" + hashlib.sha256(f"{PROMPT_VERSION}|{model}|{prompt}".encode()).hexdigest()
        if self.storage:
            cached = self.storage.cache_get(cache_key)
            if cached is not None:
                totals["hits"] += 1
                return cached
        try:
            result = self.llm.review(SYSTEM_PROMPT, prompt, model)
        except Exception as error:
            logger.error("LLM review failed: %s", error)
            return None
        totals["input"] += result.input_tokens
        totals["output"] += result.output_tokens
        totals["cost"] += result.cost_inr
        totals["calls"] += 1
        if self.storage:
            self.storage.cache_put(cache_key, result.data, ttl_seconds=3 * 24 * 3600)
        return result.data

    def _empty_result(self, reason: str, started: float) -> ReviewResult:
        latency_ms = int((time.time() - started) * 1000)
        markdown = format_summary(reason, "low", [], [], 0, "none", latency_ms, 0)
        return ReviewResult(
            summary_markdown=markdown,
            summary_text=reason,
            risk_level="low",
            risk_reasons=[],
            comments=[],
            suggested_tests=[],
            findings=[],
            model="none",
            latency_ms=latency_ms,
            skipped_reason=reason,
        )


def result_to_json(result: ReviewResult) -> str:
    return json.dumps(result.__dict__, indent=2, default=str)
