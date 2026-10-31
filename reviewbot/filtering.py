"""Keeps only the best comments. Noise kills adoption, so this step matters.

1. Drop comments on lines GitHub would reject (outside the diff).
2. Drop comments below the confidence bar (per category, tuned by feedback).
3. Merge duplicates (same file, nearby lines, same issue).
4. Sort by importance and keep at most N.
"""

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
VALID_CATEGORIES = {"bug", "security", "error-handling", "performance", "rule-violation", "testing", "secret", "reliability"}


def normalise_comment(raw: dict) -> dict | None:
    try:
        line = int(raw.get("line"))
    except (TypeError, ValueError):
        return None
    try:
        start_line = int(raw.get("start_line") or line)
    except (TypeError, ValueError):
        start_line = line
    if start_line > line:
        start_line = line

    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0

    category = str(raw.get("category", "bug")).lower()
    if category not in VALID_CATEGORIES:
        category = "bug"
    severity = str(raw.get("severity", "medium")).lower()
    if severity not in SEVERITY_WEIGHT:
        severity = "medium"

    return {
        "file": str(raw.get("file", "")).lstrip("/"),
        "start_line": start_line,
        "line": line,
        "category": category,
        "severity": severity,
        "confidence": max(0.0, min(1.0, confidence)),
        "title": str(raw.get("title", "")).strip()[:120],
        "explanation": str(raw.get("explanation", "")).strip(),
        "suggestion": str(raw.get("suggestion") or ""),
        "source": raw.get("source", "llm"),
    }


def findings_to_comments(findings: list) -> list:
    """Secrets are always worth a comment, even if the LLM missed them."""
    comments = []
    for finding in findings:
        if finding["category"] != "secret":
            continue
        comments.append(
            {
                "file": finding["file"],
                "start_line": finding["line"],
                "line": finding["line"],
                "category": "secret",
                "severity": "high",
                "confidence": 0.95,
                "title": "Possible secret committed",
                "explanation": finding["message"] + " Rotate the credential, since it is now in git history.",
                "suggestion": "",
                "source": "static",
            }
        )
    return comments


def filter_comments(
    raw_comments: list,
    commentable_lines: dict,
    threshold_for,
    max_comments: int,
) -> list:
    """
    raw_comments:      comments from the LLM and static analysis
    commentable_lines: {path: set of line numbers inside the diff}
    threshold_for:     function(category) -> minimum confidence
    """
    valid = []
    for raw in raw_comments:
        comment = normalise_comment(raw)
        if comment is None or not comment["explanation"]:
            continue
        allowed = commentable_lines.get(comment["file"])
        if not allowed or comment["line"] not in allowed:
            continue
        if comment["start_line"] not in allowed:
            comment["start_line"] = comment["line"]
            comment["suggestion"] = ""
        if comment["confidence"] < threshold_for(comment["category"]):
            continue
        valid.append(comment)

    # Merge duplicates: keep the most confident comment per (file, area)
    valid.sort(key=lambda item: item["confidence"], reverse=True)
    merged = []
    for comment in valid:
        duplicate = False
        for kept in merged:
            same_file = kept["file"] == comment["file"]
            close = abs(kept["line"] - comment["line"]) <= 2
            if same_file and close and (kept["category"] == comment["category"] or kept["line"] == comment["line"]):
                duplicate = True
                break
        if not duplicate:
            merged.append(comment)

    merged.sort(key=lambda item: SEVERITY_WEIGHT[item["severity"]] * item["confidence"], reverse=True)
    return merged[:max_comments]
