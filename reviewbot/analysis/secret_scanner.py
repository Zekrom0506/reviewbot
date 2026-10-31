"""A small secret scanner: looks for API keys, tokens and private keys that
someone accidentally committed. Each pattern is a regular expression."""

import math
import re

from reviewbot.analysis import Finding

SECRET_PATTERNS = [
    ("aws-access-key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("groq-api-key", re.compile(r"\bgsk_[A-Za-z0-9]{40,}\b")),
    ("openai-api-key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9_\-]{32,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-secret-key", re.compile(r"\b(sk|rk)_live_[A-Za-z0-9]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private-key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
]

# key = "something long and random"
GENERIC_ASSIGNMENT = re.compile(
    r"""(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key)\w*\s*[:=]\s*["']([^"'\s]{8,})["']"""
)

PLACEHOLDER_WORDS = ("example", "changeme", "your", "xxxx", "dummy", "test", "placeholder", "<", "${", "os.environ")


def shannon_entropy(text: str) -> float:
    """How random a string looks. Real keys score high, words score low."""
    if not text:
        return 0.0
    counts = {}
    for character in text:
        counts[character] = counts.get(character, 0) + 1
    entropy = 0.0
    for count in counts.values():
        probability = count / len(text)
        entropy -= probability * math.log2(probability)
    return entropy


def scan_for_secrets(files: dict) -> list:
    findings = []
    for path, content in files.items():
        for line_number, line in enumerate(content.splitlines(), start=1):
            found_on_line = False
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        Finding(
                            tool="secrets",
                            file=path,
                            line=line_number,
                            rule=name,
                            message=f"Possible {name.replace('-', ' ')} committed to the repository.",
                            severity="high",
                            category="secret",
                        )
                    )
                    found_on_line = True
                    break
            if found_on_line:
                continue

            match = GENERIC_ASSIGNMENT.search(line)
            if match:
                value = match.group(2)
                lowered = value.lower()
                if any(word in lowered for word in PLACEHOLDER_WORDS):
                    continue
                if shannon_entropy(value) >= 3.0 or match.group(1).lower() in ("password", "passwd", "pwd"):
                    findings.append(
                        Finding(
                            tool="secrets",
                            file=path,
                            line=line_number,
                            rule="hardcoded-credential",
                            message=f"Hard-coded value assigned to '{match.group(1)}'. Load it from an environment variable or secret manager instead.",
                            severity="high",
                            category="secret",
                        )
                    )
    return findings
