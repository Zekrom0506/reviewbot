"""Numbers for the dashboard, computed from the DynamoDB tables."""

from collections import Counter, defaultdict


def percentile(values: list, fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def compute_stats(reviews: list, comments: list, repo_configs: list) -> dict:
    latencies = [review.get("latencyMs", 0) for review in reviews]
    costs = [float(review.get("costInr", 0)) for review in reviews]

    voted = [comment for comment in comments if comment.get("thumbsUp", 0) + comment.get("thumbsDown", 0) > 0]
    helpful = [comment for comment in voted if comment.get("feedback") == "up"]

    by_category = defaultdict(lambda: {"comments": 0, "up": 0, "down": 0})
    for comment in comments:
        entry = by_category[comment.get("category", "bug")]
        entry["comments"] += 1
        entry["up"] += int(comment.get("thumbsUp", 0))
        entry["down"] += int(comment.get("thumbsDown", 0))

    per_day = Counter(review.get("createdAt", "")[:10] for review in reviews if review.get("createdAt"))
    models = Counter(review.get("model", "?") for review in reviews)

    recent = sorted(reviews, key=lambda review: review.get("createdAt", ""), reverse=True)[:20]

    return {
        "totals": {
            "reviews": len(reviews),
            "comments": len(comments),
            "votedComments": len(voted),
            "helpfulRate": round(len(helpful) / len(voted), 3) if voted else None,
            "avgLatencySec": round(sum(latencies) / len(latencies) / 1000, 1) if latencies else 0,
            "p95LatencySec": round(percentile(latencies, 0.95) / 1000, 1),
            "avgCostInr": round(sum(costs) / len(costs), 3) if costs else 0,
            "totalCostInr": round(sum(costs), 2),
            "avgCommentsPerPr": round(len(comments) / len(reviews), 2) if reviews else 0,
            "cacheHits": sum(int(review.get("cacheHits", 0)) for review in reviews),
        },
        "riskLevels": dict(Counter(review.get("riskLevel", "low") for review in reviews)),
        "categories": dict(by_category),
        "reviewsPerDay": dict(sorted(per_day.items())),
        "models": dict(models),
        "thresholds": {config["repo"]: config.get("tunedThresholds", {}) for config in repo_configs},
        "recent": [
            {
                "repo": review.get("repo"),
                "prNumber": review.get("prNumber"),
                "riskLevel": review.get("riskLevel"),
                "commentCount": review.get("commentCount"),
                "latencySec": round(review.get("latencyMs", 0) / 1000, 1),
                "costInr": review.get("costInr"),
                "model": review.get("model"),
                "createdAt": review.get("createdAt"),
            }
            for review in recent
        ],
    }
