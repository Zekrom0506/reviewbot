"""Reads the optional .reviewbot.yml file from the repository.

Example .reviewbot.yml:

    strictness: normal          # relaxed | normal | strict
    max_comments: 5
    ignore_paths:
      - "docs/**"
      - "*.lock"
    rules:
      - "All database access must go through db.py"
      - "Never log user passwords or tokens"
"""

import fnmatch
from dataclasses import dataclass, field

import yaml

# How sure the bot must be before posting, for each strictness level.
# "strict" means more comments, so a lower bar.
STRICTNESS_TO_CONFIDENCE = {"relaxed": 0.85, "normal": 0.7, "strict": 0.55}

DEFAULT_IGNORES = [
    "*.lock",
    "package-lock.json",
    "*.min.js",
    "*.svg",
    "*.png",
    "*.jpg",
    "dist/**",
    "build/**",
    "vendor/**",
]


@dataclass
class RepoConfig:
    strictness: str = "normal"
    max_comments: int = 5
    ignore_paths: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    # Per-category confidence bars learned from 👍/👎 feedback
    tuned_thresholds: dict = field(default_factory=dict)

    def min_confidence(self, default: float) -> float:
        return STRICTNESS_TO_CONFIDENCE.get(self.strictness, default)

    def threshold_for(self, category: str, default: float) -> float:
        base = self.min_confidence(default)
        tuned = self.tuned_thresholds.get(category)
        if tuned is None:
            return base
        return max(base, float(tuned))

    def is_ignored(self, path: str) -> bool:
        for pattern in DEFAULT_IGNORES + self.ignore_paths:
            if fnmatch.fnmatch(path, pattern):
                return True
            # "docs/**" should also match "docs/a.md"
            if pattern.endswith("/**") and path.startswith(pattern[:-3] + "/"):
                return True
        return False


def parse_repo_config(yaml_text: str | None, stored: dict | None = None) -> RepoConfig:
    config = RepoConfig()
    stored = stored or {}

    # Values saved in DynamoDB (e.g. set by an admin) come first...
    if stored.get("strictness"):
        config.strictness = stored["strictness"]
    if stored.get("rules"):
        config.rules = list(stored["rules"])
    if stored.get("ignoredPaths"):
        config.ignore_paths = list(stored["ignoredPaths"])
    config.tuned_thresholds = dict(stored.get("tunedThresholds", {}))

    # ...and the file in the repo overrides them, because developers own it.
    if yaml_text:
        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError:
            data = {}
        if isinstance(data, dict):
            if data.get("strictness") in STRICTNESS_TO_CONFIDENCE:
                config.strictness = data["strictness"]
            if isinstance(data.get("max_comments"), int):
                config.max_comments = max(1, min(20, data["max_comments"]))
            if isinstance(data.get("ignore_paths"), list):
                config.ignore_paths = [str(item) for item in data["ignore_paths"]]
            if isinstance(data.get("rules"), list):
                config.rules = [str(item) for item in data["rules"]]
    return config
