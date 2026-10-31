"""End-to-end pipeline test with a fake LLM (no network needed)."""

from conftest import SAMPLE_DIFF, SAMPLE_NEW_FILE

from reviewbot.config import Settings
from reviewbot.llm import LLMResult
from reviewbot.pipeline import ReviewInput, ReviewPipeline
from reviewbot.retrieval.embedder import HashingEmbedder
from reviewbot.retrieval.indexer import index_files
from reviewbot.retrieval.vector_store import InMemoryVectorStore


class FakeLLM:
    def __init__(self, response: dict):
        self.response = response
        self.prompts = []

    def review(self, system_prompt, user_prompt, model):
        self.prompts.append(user_prompt)
        return LLMResult(self.response, model, 1000, 200, 0.02, 500)


LLM_RESPONSE = {
    "summary": "Changes find_user to build SQL with an f-string.",
    "risk_level": "high",
    "risk_reasons": ["SQL injection"],
    "comments": [
        {
            "file": "app/auth.py",
            "start_line": 5,
            "line": 6,
            "category": "security",
            "severity": "high",
            "confidence": 0.95,
            "title": "SQL injection",
            "explanation": "User input is formatted into SQL.",
            "suggestion": '    return db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()',
        },
        {
            "file": "app/auth.py",
            "line": 1,
            "category": "bug",
            "severity": "low",
            "confidence": 0.3,
            "title": "weak",
            "explanation": "Speculative.",
            "suggestion": "",
        },
    ],
    "suggested_tests": [{"file": "app/auth.py", "function": "find_user", "cases": ["name with a quote"]}],
}


def build_pipeline(llm):
    store = InMemoryVectorStore()
    embedder = HashingEmbedder()
    index_files(
        store,
        embedder,
        "me/shop",
        {
            "app/views.py": "def profile(db, name):\n    user = find_user(db, name)\n    return user\n",
            "app/auth.py": SAMPLE_NEW_FILE,
        },
    )
    return ReviewPipeline(Settings(), llm, store, embedder)


def test_pipeline_produces_filtered_review():
    llm = FakeLLM(LLM_RESPONSE)
    pipeline = build_pipeline(llm)
    result = pipeline.run(
        ReviewInput(repo="me/shop", title="Refactor auth", body="", diff_text=SAMPLE_DIFF,
                    files={"app/auth.py": SAMPLE_NEW_FILE})
    )

    assert result.risk_level == "high"
    lines = sorted(comment["line"] for comment in result.comments)
    # LLM SQL comment (line 6) + deterministic secret comment (line 9); weak one dropped
    assert lines == [6, 9]
    assert result.comments[0]["confidence"] >= 0.9
    assert "ReviewBot summary" in result.summary_markdown
    assert "find_user" in result.summary_markdown  # suggested tests section
    assert result.cost_inr == 0.02
    assert result.model == Settings().large_model  # high heuristic risk -> large model

    prompt = llm.prompts[0]
    assert "Caller of find_user" in prompt  # retrieval worked
    assert "secrets/github-token" in prompt  # static findings were passed to the LLM


def test_pipeline_skips_ignored_files():
    llm = FakeLLM(LLM_RESPONSE)
    pipeline = build_pipeline(llm)
    diff = SAMPLE_DIFF.replace("app/auth.py", "package-lock.json")
    result = pipeline.run(ReviewInput(repo="me/shop", title="x", body="", diff_text=diff, files={}))
    assert result.skipped_reason
    assert llm.prompts == []


def test_pipeline_survives_llm_failure():
    class BrokenLLM:
        def review(self, *args):
            raise RuntimeError("down")

    pipeline = build_pipeline(BrokenLLM())
    result = pipeline.run(
        ReviewInput(repo="me/shop", title="x", body="", diff_text=SAMPLE_DIFF, files={"app/auth.py": SAMPLE_NEW_FILE})
    )
    # The secret is still reported thanks to static analysis
    assert [comment["category"] for comment in result.comments] == ["secret"]
