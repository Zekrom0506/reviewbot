"""Turns a GitHub webhook into zero or more queue jobs.

Shared by the local web server and the AWS Lambda webhook handler, so the
logic is written once.
"""

REVIEW_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


def jobs_from_event(event_name: str, payload: dict) -> list:
    installation_id = (payload.get("installation") or {}).get("id")
    if not installation_id:
        return []

    if event_name == "pull_request":
        if payload.get("action") not in REVIEW_ACTIONS:
            return []
        pr = payload["pull_request"]
        if pr.get("draft"):
            return []
        return [
            {
                "type": "review_pr",
                "repo": payload["repository"]["full_name"],
                "pr_number": pr["number"],
                "head_sha": pr["head"]["sha"],
                "installation_id": installation_id,
            }
        ]

    if event_name == "push":
        repository = payload.get("repository", {})
        default_branch = repository.get("default_branch", "main")
        if payload.get("ref") != f"refs/heads/{default_branch}" or payload.get("deleted"):
            return []
        return [
            {
                "type": "index_repo",
                "repo": repository["full_name"],
                "ref": payload["after"],
                "installation_id": installation_id,
            }
        ]

    if event_name in ("installation", "installation_repositories"):
        if payload.get("action") not in ("created", "added"):
            return []
        repositories = payload.get("repositories") or payload.get("repositories_added") or []
        return [
            {
                "type": "index_repo",
                "repo": repository["full_name"],
                "ref": "HEAD",
                "installation_id": installation_id,
            }
            for repository in repositories
        ]

    return []
