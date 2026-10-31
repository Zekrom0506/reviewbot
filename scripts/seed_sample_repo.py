"""Fills an empty GitHub repo with TinyShop and opens PRs with seeded bugs.

Steps for you:
  1. Create an EMPTY repo on GitHub (no README), e.g. reviewbot-sample
  2. Install your ReviewBot App on it
  3. Run:
       docker compose run --rm worker python -m scripts.seed_sample_repo --repo YOUR_NAME/reviewbot-sample

Each PR comes from the evaluation set (eval/cases.py), so you can compare
what the bot says with the bug we planted.
"""

import argparse
import random
import time

from eval.build import apply_case, load_sample_repo
from eval.cases import BUGGY_CASES, CLEAN_CASES
from reviewbot.config import load_settings
from reviewbot.github_client import GitHubClient, get_repo_installation_id

DEFAULT_CASES = [
    "auth-sql-injection",
    "auth-hardcoded-key",
    "cart-float-money",
    "payments-refund-swallows-error",
    "orders-idor",
    "new-notifications",
    "utils-paginate-off-by-one",
    "clean-clamp",
]


def upload_base_repo(github: GitHubClient, repo: str, branch: str) -> None:
    files = load_sample_repo()
    print(f"Uploading {len(files)} files to {repo}...")
    for path, content in files.items():
        existing_sha = github.get_file_sha(repo, path, branch)
        github.put_file(repo, path, content, f"Add {path}", branch, sha=existing_sha)
        print(f"  + {path}")


def open_case_pr(github: GitHubClient, repo: str, base_branch: str, case: dict, base_files: dict) -> str:
    branch = f"seed/{case['id']}-{random.randint(1000, 9999)}"
    base_sha = github.get_branch_sha(repo, base_branch)
    github.create_branch(repo, branch, base_sha)
    for path, content in apply_case(base_files, case).items():
        sha = github.get_file_sha(repo, path, branch)
        github.put_file(repo, path, content, case["title"], branch, sha=sha)
    pr = github.open_pull_request(
        repo,
        title=case["title"],
        head=branch,
        base=base_branch,
        body="Seeded test PR for ReviewBot (case `" + case["id"] + "`).",
    )
    return pr["html_url"]


def main():
    parser = argparse.ArgumentParser(description="Seed a sample repo with test PRs")
    parser.add_argument("--repo", required=True, help="owner/name of an empty repo with the App installed")
    parser.add_argument("--cases", default=",".join(DEFAULT_CASES), help="comma-separated case ids, or 'all'")
    parser.add_argument("--skip-upload", action="store_true", help="repo already has the base code")
    parser.add_argument("--delay", type=float, default=20.0, help="seconds between PRs (free-tier LLM limits)")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.github_app_id:
        raise SystemExit("GitHub App is not set up yet. Open http://localhost:8000/setup first.")

    installation_id = get_repo_installation_id(settings, args.repo)
    github = GitHubClient(settings, installation_id)
    base_branch = "main"

    if not args.skip_upload:
        upload_base_repo(github, args.repo, base_branch)
        print("Waiting 30s so the bot can index the code...")
        time.sleep(30)

    all_cases = {case["id"]: case for case in BUGGY_CASES + CLEAN_CASES}
    wanted = list(all_cases) if args.cases == "all" else args.cases.split(",")
    base_files = load_sample_repo()
    for number, case_id in enumerate(wanted):
        case = all_cases[case_id.strip()]
        url = open_case_pr(github, args.repo, base_branch, case, base_files)
        print(f"Opened {url}")
        if number < len(wanted) - 1:
            time.sleep(args.delay)
    print("Done. Reviews should appear on each PR within about a minute.")


if __name__ == "__main__":
    main()
