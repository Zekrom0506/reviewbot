"""The prompt we send to the LLM. Changing this file changes the bot's
behaviour more than any other file, so the eval script (eval/run_eval.py)
should be re-run after edits."""

PROMPT_VERSION = "v3"

SYSTEM_PROMPT = """You are a senior software engineer reviewing a pull request.
Your comments must be HIGH SIGNAL. Developers ignore noisy bots.

Comment ONLY on real problems that a careful senior reviewer would flag:
- bugs and logic errors (wrong condition, off-by-one, None/null handling, wrong variable)
- security issues (injection, missing auth checks, secrets, unsafe deserialization)
- missing or swallowed error handling that can lose data or crash
- broken contracts with callers shown in the related code
- violations of the repository rules listed below

Do NOT comment on: formatting, naming taste, missing docstrings, things that
are already correct, or speculative "consider" advice. If nothing is wrong,
return an empty comments list. Fewer, correct comments beat many weak ones.

Static analysis findings are given as hints. Confirm them against the code and
explain them in plain language; drop the ones that are false alarms.

Line numbers: every diff line is prefixed with its line number in the NEW file.
Only comment on lines marked with "+" (added) or unchanged lines inside the diff.

Confidence: a number from 0.0 to 1.0. Use >= 0.8 only when you are sure the
issue is real and would cause a problem. Use < 0.5 for anything speculative.

"suggestion" must be the exact replacement code for the lines from
"start_line" to "line" (inclusive), with correct indentation, or "" when a
one-click fix is not possible.

Respond with ONLY a JSON object in this exact shape:
{
  "summary": "2-4 sentences: what the PR changes and its likely impact",
  "risk_level": "low" | "medium" | "high",
  "risk_reasons": ["short reason", "..."],
  "comments": [
    {
      "file": "path/in/repo.py",
      "start_line": 12,
      "line": 12,
      "category": "bug" | "security" | "error-handling" | "performance" | "rule-violation" | "testing",
      "severity": "low" | "medium" | "high",
      "confidence": 0.0,
      "title": "short title",
      "explanation": "why this is a problem, in 1-3 sentences",
      "suggestion": "replacement code or empty string"
    }
  ],
  "suggested_tests": [
    {"file": "path/in/repo.py", "function": "name", "cases": ["test case description", "..."]}
  ]
}"""


def build_user_prompt(
    repo: str,
    pr_title: str,
    pr_body: str,
    diff_text: str,
    context_text: str,
    findings: list,
    rules: list,
    untested_functions: list,
    heuristic_reasons: list,
) -> str:
    parts = [f"Repository: {repo}", f"PR title: {pr_title}"]
    if pr_body:
        parts.append(f"PR description:\n{pr_body[:1500]}")

    if rules:
        parts.append("Repository rules (from .reviewbot.yml):\n" + "\n".join(f"- {rule}" for rule in rules))

    if heuristic_reasons:
        parts.append("Automatic risk signals:\n" + "\n".join(f"- {reason}" for reason in heuristic_reasons))

    if findings:
        lines = [
            f"- {item['file']}:{item['line']} [{item['tool']}/{item['rule']}] {item['message']}" for item in findings
        ]
        parts.append("Static analysis findings on changed lines:\n" + "\n".join(lines[:40]))
    else:
        parts.append("Static analysis findings on changed lines: none")

    if untested_functions:
        names = ", ".join(f"{item['function']} ({item['file']})" for item in untested_functions[:8])
        parts.append(f"Changed functions with no existing tests found in the repo: {names}")

    if context_text:
        parts.append("Related code from the repository (callers, tests, similar code):\n" + context_text)

    parts.append("Diff to review:\n" + diff_text)
    return "\n\n".join(parts)
