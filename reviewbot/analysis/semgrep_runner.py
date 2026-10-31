"""Runs Semgrep with our own rule file (config/semgrep_rules.yml).

We ship the rules with the project instead of downloading them so the bot
works offline and gives the same results every time.
"""

import json
import os
import subprocess

from reviewbot.analysis import Finding

RULES_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "config", "semgrep_rules.yml")
SUPPORTED_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx")


def run_semgrep(folder: str, paths: list) -> list:
    targets = [path for path in paths if path.endswith(SUPPORTED_EXTENSIONS)]
    if not targets:
        return []

    rules_path = os.environ.get("SEMGREP_RULES", os.path.abspath(RULES_FILE))
    command = [
        "semgrep",
        "scan",
        "--config",
        rules_path,
        "--json",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
    ]
    command.extend(targets)
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=120)
    if not result.stdout.strip():
        return []

    findings = []
    for item in json.loads(result.stdout).get("results", []):
        extra = item.get("extra", {})
        metadata = extra.get("metadata", {})
        semgrep_severity = extra.get("severity", "WARNING")
        severity = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}.get(semgrep_severity, "medium")
        rule_id = item.get("check_id", "semgrep").split(".")[-1]
        findings.append(
            Finding(
                tool="semgrep",
                file=item["path"],
                line=item["start"]["line"],
                rule=rule_id,
                message=extra.get("message", "").strip(),
                severity=severity,
                category=metadata.get("category", "security"),
            )
        )
    return findings
