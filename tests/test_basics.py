from conftest import SAMPLE_DIFF, SAMPLE_NEW_FILE

from reviewbot.analysis.secret_scanner import scan_for_secrets
from reviewbot.diff_parser import changed_function_names, chunk_files, parse_diff
from reviewbot.filtering import filter_comments
from reviewbot.repo_config import parse_repo_config
from reviewbot.risk import assess_risk
from reviewbot.signature import compute_signature, verify_signature
from reviewbot.webhooks import jobs_from_event


def test_signature_accepts_valid_and_rejects_invalid():
    body = b'{"action":"opened"}'
    signature = compute_signature("secret", body)
    assert verify_signature("secret", body, signature)
    assert not verify_signature("wrong", body, signature)
    assert not verify_signature("secret", body, "")


def test_signature_survives_smee_reformatting():
    original = b'{"a":1,"b":"x"}'
    reformatted = b'{"a": 1, "b": "x"}'
    signature = compute_signature("secret", original)
    assert verify_signature("secret", reformatted, signature)


def test_parse_diff_tracks_new_line_numbers():
    files = parse_diff(SAMPLE_DIFF)
    assert len(files) == 1
    file_diff = files[0]
    assert file_diff.path == "app/auth.py"
    assert file_diff.added_line_numbers() == {4, 5, 6, 7, 8, 9}
    assert 1 in file_diff.commentable_line_numbers()
    # The added line 5 must be the f-string query
    added = {line.new_number: line.text for hunk in file_diff.hunks for line in hunk.lines if line.kind == "add"}
    assert "f\"SELECT" in added[5]
    assert "find_user" in changed_function_names(file_diff)


def test_chunk_files_respects_limit():
    files = parse_diff(SAMPLE_DIFF) * 3
    chunks = chunk_files(files, max_lines=10)
    assert len(chunks) == 3


def test_secret_scanner_finds_github_token():
    findings = scan_for_secrets({"app/auth.py": SAMPLE_NEW_FILE})
    assert any(finding.rule == "github-token" and finding.line == 9 for finding in findings)


def test_secret_scanner_ignores_placeholders():
    findings = scan_for_secrets({"x.py": 'API_KEY = "your-api-key-here"\nPASSWORD = os.environ["PW"]\n'})
    assert findings == []


def test_filter_drops_low_confidence_out_of_diff_and_duplicates():
    commentable = {"a.py": {1, 2, 3, 10}}
    raw = [
        {"file": "a.py", "line": 2, "confidence": 0.9, "category": "bug", "severity": "high", "explanation": "x"},
        {"file": "a.py", "line": 3, "confidence": 0.8, "category": "bug", "severity": "high", "explanation": "dup"},
        {"file": "a.py", "line": 10, "confidence": 0.4, "category": "bug", "severity": "high", "explanation": "weak"},
        {"file": "a.py", "line": 50, "confidence": 0.99, "category": "bug", "severity": "high", "explanation": "outside"},
        {"file": "b.py", "line": 1, "confidence": 0.99, "category": "bug", "severity": "high", "explanation": "other"},
    ]
    kept = filter_comments(raw, commentable, threshold_for=lambda category: 0.7, max_comments=5)
    assert [comment["line"] for comment in kept] == [2]


def test_filter_caps_comment_count():
    commentable = {"a.py": set(range(1, 100))}
    raw = [
        {"file": "a.py", "line": line, "confidence": 0.9, "category": "bug", "severity": "medium", "explanation": "x"}
        for line in range(1, 100, 10)
    ]
    assert len(filter_comments(raw, commentable, lambda category: 0.5, max_comments=3)) == 3


def test_repo_config_parsing_and_ignores():
    config = parse_repo_config("strictness: strict\nignore_paths: ['docs/**']\nrules: ['no prints']\n")
    assert config.min_confidence(0.7) == 0.55
    assert config.is_ignored("docs/readme.md")
    assert config.is_ignored("package-lock.json")
    assert not config.is_ignored("app/main.py")
    assert config.rules == ["no prints"]


def test_tuned_threshold_never_below_base():
    config = parse_repo_config(None, {"tunedThresholds": {"bug": 0.5, "testing": 0.9}})
    assert config.threshold_for("bug", 0.7) == 0.7
    assert config.threshold_for("testing", 0.7) == 0.9


def test_risk_flags_auth_and_missing_tests():
    files = parse_diff(SAMPLE_DIFF)
    findings = [{"category": "secret", "severity": "high"}]
    level, reasons = assess_risk(files, findings)
    assert level == "high"
    assert "touches auth logic" in reasons
    assert "no tests added" in reasons


def test_webhook_events_become_jobs():
    pr_payload = {
        "action": "opened",
        "installation": {"id": 5},
        "repository": {"full_name": "me/repo", "default_branch": "main"},
        "pull_request": {"number": 3, "draft": False, "head": {"sha": "abc"}},
    }
    jobs = jobs_from_event("pull_request", pr_payload)
    assert jobs[0]["type"] == "review_pr" and jobs[0]["pr_number"] == 3

    pr_payload["action"] = "closed"
    assert jobs_from_event("pull_request", pr_payload) == []

    push_payload = {
        "ref": "refs/heads/main",
        "after": "def",
        "installation": {"id": 5},
        "repository": {"full_name": "me/repo", "default_branch": "main"},
    }
    assert jobs_from_event("push", push_payload)[0]["type"] == "index_repo"
    push_payload["ref"] = "refs/heads/feature"
    assert jobs_from_event("push", push_payload) == []
