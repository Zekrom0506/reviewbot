"""End-to-end test of a live review against a fake GitHub API.

The fake GitHub below implements just the endpoints ReviewBot calls, so we
can check the whole flow: token exchange, diff download, indexing, review
posting, labels and saving to DynamoDB.
"""

import base64
import hashlib
from types import SimpleNamespace

from conftest import SAMPLE_DIFF, SAMPLE_NEW_FILE
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from moto import mock_aws

import reviewbot.github_client as github_client
from reviewbot.config import Settings
from reviewbot.github_review import review_pull_request
from reviewbot.llm import LLMResult
from reviewbot.retrieval.embedder import HashingEmbedder
from reviewbot.retrieval.vector_store import InMemoryVectorStore
from reviewbot.storage import Storage

VIEWS_FILE = "def profile(db, name):\n    return find_user(db, name)\n"


def blob_sha(content: str) -> str:
    return hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest()


def encode(content: str) -> str:
    return base64.b64encode(content.encode()).decode()


def build_fake_github(posted: dict) -> FastAPI:
    fake = FastAPI()
    blobs = {blob_sha(SAMPLE_NEW_FILE): SAMPLE_NEW_FILE, blob_sha(VIEWS_FILE): VIEWS_FILE}

    @fake.post("/app/installations/{installation_id}/access_tokens", status_code=201)
    def token(installation_id: int):
        return {"token": "installation-token"}

    @fake.get("/repos/me/shop/pulls/7")
    def pull(request: Request):
        if "diff" in request.headers.get("accept", ""):
            return PlainTextResponse(SAMPLE_DIFF)
        return {"title": "Refactor auth", "body": "", "draft": False,
                "head": {"sha": "headsha"}, "base": {"ref": "main"}}

    @fake.get("/repos/me/shop/pulls/7/files")
    def files():
        return [{"filename": "app/auth.py", "status": "modified", "changes": 6, "sha": blob_sha(SAMPLE_NEW_FILE)}]

    @fake.get("/repos/me/shop/git/blobs/{sha}")
    def blob(sha: str):
        return {"content": encode(blobs[sha]), "encoding": "base64"}

    @fake.get("/repos/me/shop/git/ref/heads/main")
    def ref():
        return {"object": {"sha": "mainsha"}}

    @fake.get("/repos/me/shop/git/trees/mainsha")
    def tree():
        return {"tree": [
            {"path": "app/auth.py", "type": "blob", "sha": blob_sha(SAMPLE_NEW_FILE), "size": 100},
            {"path": "app/views.py", "type": "blob", "sha": blob_sha(VIEWS_FILE), "size": 50},
        ]}

    @fake.get("/repos/me/shop/contents/.reviewbot.yml")
    def config():
        return {"content": encode("strictness: normal\nrules:\n  - Use query parameters\n"), "encoding": "base64"}

    @fake.post("/repos/me/shop/pulls/7/reviews")
    async def create_review(request: Request):
        posted["review"] = await request.json()
        return {"id": 99}

    @fake.get("/repos/me/shop/pulls/7/reviews/99/comments")
    def review_comments():
        return [{"id": 1000 + index, "path": c["path"], "line": c["line"]}
                for index, c in enumerate(posted["review"]["comments"])]

    @fake.post("/repos/me/shop/labels", status_code=201)
    def create_label():
        return {}

    @fake.get("/repos/me/shop/issues/7/labels")
    def labels():
        return []

    @fake.post("/repos/me/shop/issues/7/labels")
    async def add_label(request: Request):
        posted["labels"] = (await request.json())["labels"]
        return []

    return fake


def make_requests_shim(client: TestClient):
    """Sends requests' calls to the fake app instead of the internet."""

    def request(method, url, headers=None, timeout=None, params=None, json=None):
        path = url.replace("https://api.github.com", "")
        return client.request(method, path, headers=headers, params=params, json=json)

    return SimpleNamespace(
        request=request,
        post=lambda url, **kwargs: request("POST", url, **kwargs),
        get=lambda url, **kwargs: request("GET", url, **kwargs),
    )


class FakeLLM:
    def review(self, system_prompt, user_prompt, model):
        data = {
            "summary": "Builds SQL with an f-string.",
            "risk_level": "high",
            "risk_reasons": ["SQL injection"],
            "comments": [{"file": "app/auth.py", "start_line": 5, "line": 5, "category": "security",
                          "severity": "high", "confidence": 0.93, "title": "SQL injection",
                          "explanation": "Name is formatted into SQL.", "suggestion": "    query = \"...\""}],
            "suggested_tests": [],
        }
        return LLMResult(data, model, 1500, 300, 0.05, 900)


@mock_aws
def test_full_review_flow(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
    settings = Settings(github_app_id="1", github_private_key=pem, aws_region="ap-south-1")

    posted = {}
    monkeypatch.setattr(github_client, "requests", make_requests_shim(TestClient(build_fake_github(posted))))

    storage = Storage(settings)
    storage.create_tables_if_missing()
    store = InMemoryVectorStore()

    job = {"type": "review_pr", "repo": "me/shop", "pr_number": 7, "installation_id": 5}
    result = review_pull_request(settings, job, FakeLLM(), store, HashingEmbedder(), storage)

    assert result["risk"] == "high"
    assert store.chunk_count("me/shop") > 0  # repo was indexed before the first review
    review = posted["review"]
    assert review["event"] == "COMMENT" and review["commit_id"] == "headsha"
    assert "ReviewBot summary" in review["body"]
    assert sorted(comment["line"] for comment in review["comments"]) == [5, 9]
    assert any("```suggestion" in comment["body"] for comment in review["comments"])
    assert posted["labels"] == ["risk: high"]

    saved = storage.list_reviews()[0]
    assert saved["prNumber"] == 7 and saved["commentCount"] == 2
    assert all(comment["githubCommentId"] >= 1000 for comment in storage.list_comments())
