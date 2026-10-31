"""Builds the Markdown that appears on GitHub."""

RISK_BADGE = {"low": "🟢 Low", "medium": "🟡 Medium", "high": "🔴 High"}
SEVERITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🔵"}


def format_inline_comment(comment: dict) -> str:
    icon = SEVERITY_ICON.get(comment["severity"], "🔵")
    title = comment["title"] or comment["category"].replace("-", " ").title()
    lines = [
        f"{icon} **{title}** · `{comment['category']}` · confidence {comment['confidence']:.0%}",
        "",
        comment["explanation"],
    ]
    if comment.get("suggestion"):
        suggestion = comment["suggestion"].rstrip("\n")
        lines += ["", "```suggestion", suggestion, "```"]
    lines += ["", "<sub>React 👍 or 👎 to help ReviewBot learn what is useful.</sub>"]
    return "\n".join(lines)


def format_summary(
    summary: str,
    risk_level: str,
    risk_reasons: list,
    suggested_tests: list,
    comment_count: int,
    model: str,
    latency_ms: int,
    static_count: int,
) -> str:
    reasons = ", ".join(risk_reasons) if risk_reasons else "no notable risk signals"
    lines = [
        "## 🤖 ReviewBot summary",
        "",
        summary.strip() or "No summary available.",
        "",
        f"**Risk:** {RISK_BADGE.get(risk_level, risk_level)} — {reasons}",
        "",
    ]

    if comment_count:
        lines.append(f"I left **{comment_count}** inline comment(s) on the most important issues.")
    else:
        lines.append("I did not find any high-confidence issues. ✅")

    if suggested_tests:
        lines += ["", "<details><summary>🧪 Suggested test cases</summary>", ""]
        for test in suggested_tests[:5]:
            lines.append(f"**`{test.get('function', '?')}`** in `{test.get('file', '?')}`")
            for case in test.get("cases", [])[:5]:
                lines.append(f"- {case}")
            lines.append("")
        lines.append("</details>")

    lines += [
        "",
        f"<sub>Model: {model} · {static_count} static-analysis finding(s) checked · "
        f"reviewed in {latency_ms / 1000:.1f}s</sub>",
    ]
    return "\n".join(lines)


def to_github_comment(comment: dict) -> dict:
    """Shape GitHub's 'create review' API expects for one inline comment."""
    payload = {
        "path": comment["file"],
        "line": comment["line"],
        "side": "RIGHT",
        "body": format_inline_comment(comment),
    }
    if comment["start_line"] < comment["line"]:
        payload["start_line"] = comment["start_line"]
        payload["start_side"] = "RIGHT"
    return payload
