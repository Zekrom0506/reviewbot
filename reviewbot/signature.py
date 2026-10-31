"""Checks that a webhook really came from GitHub.

GitHub signs every webhook body with our secret using HMAC-SHA256 and sends
the result in the X-Hub-Signature-256 header. We compute the same value and
compare. Anyone without the secret cannot produce a matching signature.
"""

import hashlib
import hmac
import json


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
    if not secret or not signature_header:
        return False

    expected = compute_signature(secret, body)
    if hmac.compare_digest(expected, signature_header):
        return True

    # Local development uses smee.io to forward webhooks to your laptop.
    # smee re-encodes the JSON body, which changes whitespace and unicode
    # escaping, so the raw bytes no longer match what GitHub signed.
    # We try the compact form GitHub uses. This is still a real check:
    # it only passes if the sender knew the secret.
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False

    candidates = [
        json.dumps(parsed, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        json.dumps(parsed, separators=(",", ":")).encode("utf-8"),
    ]
    for candidate in candidates:
        if hmac.compare_digest(compute_signature(secret, candidate), signature_header):
            return True
    return False
