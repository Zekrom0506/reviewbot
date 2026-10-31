"""Static analysis: cheap, deterministic checks that run before the LLM."""

import logging
import os
import tempfile
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    tool: str  # "ruff", "semgrep" or "secrets"
    file: str
    line: int
    rule: str
    message: str
    severity: str  # "low", "medium", "high"
    category: str  # "bug", "security", "secret", "style", ...

    def to_dict(self) -> dict:
        return asdict(self)


def write_files_to_temp_dir(files: dict) -> str:
    """Static analysis tools read files from disk, so we write the PR's
    version of each changed file into a temporary folder."""
    folder = tempfile.mkdtemp(prefix="reviewbot-")
    for path, content in files.items():
        full_path = os.path.join(folder, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as handle:
            handle.write(content)
    return folder


def run_static_analysis(files: dict, changed_lines: dict | None) -> list:
    """Run every tool and keep only findings on lines the PR touched.

    files:         {path: new file content}
    changed_lines: {path: set of new-side line numbers in the diff},
                   or None to keep every finding in the files
    """
    from reviewbot.analysis.ruff_runner import run_ruff
    from reviewbot.analysis.secret_scanner import scan_for_secrets
    from reviewbot.analysis.semgrep_runner import run_semgrep

    if not files:
        return []

    folder = write_files_to_temp_dir(files)
    findings = []
    for runner in (run_ruff, run_semgrep):
        try:
            findings.extend(runner(folder, list(files.keys())))
        except Exception as error:  # a broken tool must never break the review
            logger.warning("%s failed: %s", runner.__name__, error)
    findings.extend(scan_for_secrets(files))

    relevant = []
    seen = set()
    for finding in findings:
        if changed_lines is not None and finding.line not in changed_lines.get(finding.file, set()):
            continue
        key = (finding.file, finding.line, finding.rule)
        if key in seen:
            continue
        seen.add(key)
        relevant.append(finding)
    return relevant
