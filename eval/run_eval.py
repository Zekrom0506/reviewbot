"""Measures how good the reviewer is on PRs with known, seeded bugs.

Usage (inside Docker):
    docker compose run --rm worker python -m eval.run_eval
    docker compose run --rm worker python -m eval.run_eval --limit 10 --no-retrieval

Metrics:
  catch rate          seeded bugs that got a comment / all seeded bugs
  false-positive rate comments that matched no seeded bug / all comments
  clean-PR noise      clean PRs that received any comment / all clean PRs
  latency and cost    per PR, from the real LLM calls

A comment "catches" a bug when it is on the same file and its line range
(start_line..line, widened by 2 lines) contains the bug's line.
"""

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from eval.build import build_case_diff, bug_line_numbers, load_sample_repo
from eval.cases import ALL_CASES
from reviewbot.config import load_settings
from reviewbot.llm import LLMClient
from reviewbot.pipeline import ReviewInput, ReviewPipeline
from reviewbot.repo_config import parse_repo_config
from reviewbot.retrieval.embedder import get_embedder
from reviewbot.retrieval.indexer import index_files
from reviewbot.retrieval.vector_store import InMemoryVectorStore

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
RESULTS_DIR = Path(__file__).resolve().parent / "results"
LINE_TOLERANCE = 2
REPO_NAME = "eval/tinyshop"


def comment_matches_bug(comment: dict, bug: tuple) -> bool:
    path, line = bug
    if comment["file"] != path:
        return False
    return comment["start_line"] - LINE_TOLERANCE <= line <= comment["line"] + LINE_TOLERANCE


def evaluate_case(pipeline, base_files: dict, config, case: dict) -> dict:
    diff_text, changed = build_case_diff(base_files, case)
    bugs = bug_line_numbers(changed, case)
    result = pipeline.run(
        ReviewInput(repo=REPO_NAME, title=case["title"], body="", diff_text=diff_text, files=changed, config=config)
    )

    caught = [bug for bug in bugs if any(comment_matches_bug(comment, bug) for comment in result.comments)]
    false_positives = [
        comment for comment in result.comments if not any(comment_matches_bug(comment, bug) for bug in bugs)
    ]
    return {
        "id": case["id"],
        "clean": not bugs,
        "bugs": len(bugs),
        "caught": len(caught),
        "comments": len(result.comments),
        "false_positives": len(false_positives),
        "risk": result.risk_level,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "cost_inr": result.cost_inr,
        "llm_failed": result.llm_calls == 0 and not result.skipped_reason,
        "comment_details": [
            {"file": c["file"], "line": c["line"], "category": c["category"], "confidence": c["confidence"],
             "title": c["title"], "source": c["source"]}
            for c in result.comments
        ],
    }


def summarise(rows: list, settings) -> dict:
    buggy = [row for row in rows if not row["clean"]]
    clean = [row for row in rows if row["clean"]]
    total_bugs = sum(row["bugs"] for row in buggy)
    caught = sum(row["caught"] for row in buggy)
    comments = sum(row["comments"] for row in rows)
    false_positives = sum(row["false_positives"] for row in rows)
    latencies = [row["latency_ms"] for row in rows]
    costs = [row["cost_inr"] for row in rows]
    return {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases": len(rows),
        "seeded_bugs": total_bugs,
        "caught": caught,
        "catch_rate": round(caught / total_bugs, 3) if total_bugs else None,
        "comments": comments,
        "false_positives": false_positives,
        "false_positive_rate": round(false_positives / comments, 3) if comments else 0.0,
        "clean_prs": len(clean),
        "noisy_clean_prs": sum(1 for row in clean if row["comments"] > 0),
        "avg_latency_s": round(sum(latencies) / len(latencies) / 1000, 1) if latencies else 0,
        "avg_cost_inr": round(sum(costs) / len(costs), 3) if costs else 0,
        "llm_failures": sum(1 for row in rows if row["llm_failed"]),
        "small_model": settings.small_model,
        "large_model": settings.large_model,
        "min_confidence": settings.min_confidence,
    }


def write_report(summary: dict, rows: list, label: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"{stamp}-{label}.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=2))

    lines = [
        f"# Evaluation report ({label})",
        "",
        f"Run on {summary['date']} with {summary['small_model']} / {summary['large_model']}, "
        f"min confidence {summary['min_confidence']}.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Seeded bugs caught | **{summary['caught']} of {summary['seeded_bugs']}** ({(summary['catch_rate'] or 0):.0%}) |",
        f"| False-positive rate | **{summary['false_positive_rate']:.0%}** "
        f"({summary['false_positives']} of {summary['comments']} comments) |",
        f"| Clean PRs with any comment | {summary['noisy_clean_prs']} of {summary['clean_prs']} |",
        f"| Average review time | {summary['avg_latency_s']} s |",
        f"| Average cost per PR | ₹{summary['avg_cost_inr']} |",
        f"| LLM failures | {summary['llm_failures']} |",
        "",
        "| Case | Bugs | Caught | Comments | False alarms | Risk | Model |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['bugs']} | {row['caught']} | {row['comments']} | {row['false_positives']} "
            f"| {row['risk']} | {row['model'].split('/')[-1]} |"
        )
    report_path = RESULTS_DIR / f"latest-{label}.md"
    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="Run ReviewBot on the seeded-bug evaluation set")
    parser.add_argument("--limit", type=int, default=0, help="only run the first N cases")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--no-retrieval", action="store_true", help="ablation: skip the code index")
    parser.add_argument("--sleep", type=float, default=2.0, help="seconds between cases (free-tier rate limits)")
    parser.add_argument("--label", default="", help="name used in the report file")
    args = parser.parse_args()

    settings = load_settings()
    base_files = load_sample_repo()
    config = parse_repo_config(base_files.get(".reviewbot.yml"))

    store = InMemoryVectorStore()
    embedder = get_embedder(settings.embedding_model)
    if not args.no_retrieval:
        print("Indexing sample repo...")
        index_files(store, embedder, REPO_NAME, base_files)

    pipeline = ReviewPipeline(settings, LLMClient(settings), store, embedder, storage=None)

    cases = ALL_CASES
    if args.only:
        wanted = set(args.only.split(","))
        cases = [case for case in cases if case["id"] in wanted]
    if args.limit:
        cases = cases[: args.limit]

    rows = []
    for number, case in enumerate(cases, start=1):
        row = evaluate_case(pipeline, base_files, config, case)
        rows.append(row)
        status = "clean" if row["clean"] else f"caught {row['caught']}/{row['bugs']}"
        print(f"[{number:>2}/{len(cases)}] {case['id']:<36} {status:<12} comments={row['comments']} "
              f"fp={row['false_positives']} {row['latency_ms'] / 1000:.1f}s ₹{row['cost_inr']:.3f}")
        if number < len(cases):
            time.sleep(args.sleep)

    summary = summarise(rows, settings)
    label = args.label or ("no-retrieval" if args.no_retrieval else "full")
    report = write_report(summary, rows, label)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nReport written to {report}")


if __name__ == "__main__":
    main()
