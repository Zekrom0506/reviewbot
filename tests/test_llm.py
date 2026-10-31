from types import SimpleNamespace

import pytest

from reviewbot.config import Settings
from reviewbot.llm import LLMClient, choose_model, estimate_cost_inr, extract_json


def test_extract_json_handles_fences_and_chatter():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here: {"b": [1, 2]} done') == {"b": [1, 2]}


def test_model_routing():
    settings = Settings()
    assert choose_model(settings, 20, "low") == settings.small_model
    assert choose_model(settings, 20, "high") == settings.large_model
    assert choose_model(settings, 500, "low") == settings.large_model


def test_cost_estimate_in_rupees():
    settings = Settings(usd_to_inr=100.0)
    # 1M input tokens on the small model costs $0.075 = ₹7.5
    assert estimate_cost_inr(settings, settings.small_model, 1_000_000, 0) == pytest.approx(7.5)


def test_llm_client_parses_response(monkeypatch):
    settings = Settings(llm_api_key="test")
    client = LLMClient(settings)
    captured = {}

    def fake_create(**request):
        captured.update(request)
        message = SimpleNamespace(content='{"summary": "ok", "comments": []}')
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=500),
        )

    monkeypatch.setattr(client.client.chat.completions, "create", fake_create)
    result = client.review("system", "user", settings.small_model)
    assert result.data["summary"] == "ok"
    assert result.cost_inr > 0
    assert captured["extra_body"] == {"reasoning_effort": "low"}
    assert captured["response_format"] == {"type": "json_object"}
