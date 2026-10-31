"""Runs Ruff, a fast Python linter, and converts its output to Findings."""

import json
import subprocess

from reviewbot.analysis import Finding

# F = real errors (undefined names, unused imports)
# B = likely bugs (mutable default args, etc.)
# S = security problems (from the Bandit project)
# E722 = bare "except:"
RUFF_RULES = "F,B,S,E722,BLE"

# Rule prefixes that are security issues rather than plain bugs
SECURITY_PREFIXES = ("S",)
HIGH_SEVERITY_RULES = {"S105", "S106", "S307", "S602", "S608", "S301", "S506", "F821"}


def run_ruff(folder: str, paths: list) -> list:
    python_files = [path for path in paths if path.endswith(".py")]
    if not python_files:
        return []

    command = ["ruff", "check", "--isolated", "--output-format", "json", "--select", RUFF_RULES, "--exit-zero"]
    command.extend(python_files)
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=60)
    if not result.stdout.strip():
        return []

    findings = []
    for item in json.loads(result.stdout):
        code = item.get("code") or "ruff"
        # Ruff reports absolute paths; turn them back into repo paths
        file_path = item["filename"]
        if file_path.startswith(folder):
            file_path = file_path[len(folder):].lstrip("/")
        if code.startswith("S101"):  # "assert used" is noise in tests
            continue
        category = "security" if code.startswith(SECURITY_PREFIXES) else "bug"
        severity = "high" if code in HIGH_SEVERITY_RULES else "medium"
        if code.startswith("F401") or code.startswith("F841"):
            severity = "low"
            category = "maintainability"
        findings.append(
            Finding(
                tool="ruff",
                file=file_path,
                line=item["location"]["row"],
                rule=code,
                message=item["message"],
                severity=severity,
                category=category,
            )
        )
    return findings
