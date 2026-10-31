"""Collects 👍/👎 reactions on the bot's comments and tunes thresholds.

GitHub does not send a webhook when someone reacts to a comment, so we
poll: every few minutes we ask GitHub for the reactions on recent comments.

Tuning rule (simple and explainable):
  For each category with at least MIN_VOTES votes in a repo, if fewer than
  40% of votes are 👍 we raise that category's confidence bar by 0.1
  (max 0.95). If more than 80% are 👍 we lower it by 0.05 (min 0.5).
"""

import logging
from datetime import datetime, timedelta, timezone

from reviewbot.config import Settings
from reviewbot.github_client import GitHubClient, list_app_installations

logger = logging.getLogger(__name__)

MIN_VOTES = 5
LOOKBACK_DAYS = 30


def feedback_from_reactions(reactions: list) -> tuple:
    up = sum(1 for reaction in reactions if reaction.get("content") == "+1")
    down = sum(1 for reaction in reactions if reaction.get("content") == "-1")
    if up > down:
        return "up", up, down
    if down > up:
        return "down", up, down
    return "none", up, down


def sync_feedback(settings: Settings, storage) -> dict:
    installations = {}
    try:
        for installation in list_app_installations(settings):
            installations[installation["account"]["login"].lower()] = installation["id"]
    except Exception as error:
        logger.warning("Cannot list installations: %s", error)
        return {"checked": 0}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    clients = {}
    checked = 0
    changed = 0
    for comment in storage.list_comments():
        if not comment.get("githubCommentId") or comment.get("createdAt", "") < cutoff:
            continue
        owner = comment["repo"].split("/")[0].lower()
        installation_id = installations.get(owner)
        if installation_id is None:
            continue
        if installation_id not in clients:
            clients[installation_id] = GitHubClient(settings, installation_id)
        try:
            reactions = clients[installation_id].get_comment_reactions(comment["repo"], comment["githubCommentId"])
        except Exception as error:
            logger.debug("Reactions unavailable for %s: %s", comment["commentId"], error)
            continue
        feedback, up, down = feedback_from_reactions(reactions)
        checked += 1
        if feedback != comment.get("feedback") or up != comment.get("thumbsUp") or down != comment.get("thumbsDown"):
            storage.update_comment_feedback(comment["commentId"], feedback, up, down)
            changed += 1

    tuned = tune_thresholds(storage, settings.min_confidence)
    logger.info("Feedback sync: %d comments checked, %d changed, %d repos tuned", checked, changed, tuned)
    return {"checked": checked, "changed": changed, "tuned_repos": tuned}


def compute_thresholds(comments: list, current: dict, default: float) -> dict:
    votes = {}
    for comment in comments:
        up = int(comment.get("thumbsUp", 0))
        down = int(comment.get("thumbsDown", 0))
        if up + down == 0:
            continue
        category = comment.get("category", "bug")
        totals = votes.setdefault(category, [0, 0])
        totals[0] += up
        totals[1] += down

    new_thresholds = dict(current)
    for category, (up, down) in votes.items():
        if up + down < MIN_VOTES:
            continue
        helpful_rate = up / (up + down)
        threshold = float(current.get(category, default))
        if helpful_rate < 0.4:
            threshold = min(0.95, threshold + 0.1)
        elif helpful_rate > 0.8:
            threshold = max(0.5, threshold - 0.05)
        new_thresholds[category] = round(threshold, 2)
    return new_thresholds


def tune_thresholds(storage, default: float) -> int:
    repos = {comment["repo"] for comment in storage.list_comments()}
    tuned = 0
    for repo in repos:
        config = storage.get_repo_config(repo)
        current = config.get("tunedThresholds", {})
        updated = compute_thresholds(storage.list_comments_for_repo(repo), current, default)
        if updated != current:
            config["tunedThresholds"] = updated
            storage.save_repo_config(config)
            tuned += 1
    return tuned
