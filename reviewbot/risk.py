"""A quick rule-based risk estimate, made before calling the LLM.

It is used to (1) pick the model and (2) give the LLM concrete hints.
The final risk label is the higher of this estimate and the LLM's opinion.
"""

import re

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

SENSITIVE_AREAS = [
    (re.compile(r"auth|login|session|password|token|jwt|oauth|permission|acl|role", re.I), "touches auth logic"),
    (re.compile(r"payment|billing|invoice|checkout|refund|wallet", re.I), "touches payment code"),
    (re.compile(r"crypto|secret|security|encrypt", re.I), "touches security-sensitive code"),
    (re.compile(r"migration|schema|\.sql$", re.I), "changes the database schema"),
    (re.compile(r"\.github/workflows|dockerfile|infra/|terraform|\.tf$", re.I), "changes CI or infrastructure"),
]

SOURCE_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb")


def is_test_file(path: str) -> bool:
    name = path.split("/")[-1].lower()
    test_suffixes = ("_test.py", ".test.js", ".test.ts", ".spec.ts", ".spec.js")
    return name.startswith("test") or name.endswith(test_suffixes) or "/tests/" in "/" + path


def max_risk(first: str, second: str) -> str:
    return first if RISK_ORDER.get(first, 0) >= RISK_ORDER.get(second, 0) else second


def assess_risk(file_diffs: list, findings: list) -> tuple:
    reasons = []
    score = 0

    paths = [file_diff.path for file_diff in file_diffs]
    for pattern, reason in SENSITIVE_AREAS:
        if any(pattern.search(path) for path in paths):
            reasons.append(reason)
            score += 2

    source_changed = [path for path in paths if path.endswith(SOURCE_EXTENSIONS) and not is_test_file(path)]
    tests_changed = [path for path in paths if is_test_file(path)]
    if source_changed and not tests_changed:
        reasons.append("no tests added")
        score += 1

    total_lines = sum(file_diff.changed_line_count() for file_diff in file_diffs)
    if total_lines > 400:
        reasons.append(f"large change ({total_lines} lines)")
        score += 1

    secret_findings = [item for item in findings if item["category"] == "secret"]
    high_findings = [item for item in findings if item["severity"] == "high" and item["category"] != "secret"]
    if secret_findings:
        reasons.append("possible secret committed")
        score += 3
    if high_findings:
        reasons.append(f"{len(high_findings)} high-severity static analysis finding(s)")
        score += 2

    if score >= 4:
        level = "high"
    elif score >= 2:
        level = "medium"
    else:
        level = "low"
    return level, reasons
