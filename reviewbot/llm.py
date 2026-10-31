"""Talks to the LLM (Groq by default, any OpenAI-compatible API works).

Model routing: small, low-risk diffs go to the small fast model, big or
risky diffs go to the large model. That is the main cost control.
"""

import json
import logging
import re
import time
from dataclasses import dataclass

from reviewbot.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int
    cost_inr: float
    latency_ms: int


class LLMError(Exception):
    pass


def choose_model(settings: Settings, changed_lines: int, heuristic_risk: str) -> str:
    if heuristic_risk == "high" or changed_lines > settings.small_diff_line_limit:
        return settings.large_model
    return settings.small_model


def estimate_cost_inr(settings: Settings, model: str, input_tokens: int, output_tokens: int) -> float:
    if model == settings.large_model:
        price_in, price_out = settings.large_model_price
    else:
        price_in, price_out = settings.small_model_price
    usd = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    return round(usd * settings.usd_to_inr, 4)


def extract_json(text: str) -> dict:
    """Models sometimes wrap JSON in ```json fences or add a sentence.
    Find the outermost {...} and parse it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("No JSON object in model response")
    return json.loads(text[start:end + 1])


class LLMClient:
    def __init__(self, settings: Settings):
        from openai import OpenAI

        if not settings.llm_api_key:
            raise LLMError("GROQ_API_KEY is not set")
        self.settings = settings
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, max_retries=0)

    def review(self, system_prompt: str, user_prompt: str, model: str) -> LLMResult:
        attempts = 4
        last_error = None
        for attempt in range(attempts):
            started = time.time()
            request = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 8000,
                "response_format": {"type": "json_object"},
            }
            # gpt-oss models "think" before answering. Less thinking for the
            # small model keeps small reviews fast.
            if "gpt-oss" in model:
                effort = "medium" if model == self.settings.large_model else "low"
                request["extra_body"] = {"reasoning_effort": effort}
            try:
                response = self.client.chat.completions.create(**request)
                content = response.choices[0].message.content or ""
                data = extract_json(content)
                usage = response.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0
                return LLMResult(
                    data=data,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_inr=estimate_cost_inr(self.settings, model, input_tokens, output_tokens),
                    latency_ms=int((time.time() - started) * 1000),
                )
            except Exception as error:  # network errors, rate limits, bad JSON
                last_error = error
                wait_seconds = 2 ** attempt * 2
                message = str(error)
                if "429" in message or "rate" in message.lower():
                    wait_seconds = max(wait_seconds, 10)
                logger.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, attempts, message[:300])
                if attempt < attempts - 1:
                    time.sleep(wait_seconds)
        raise LLMError(f"LLM failed after {attempts} attempts: {last_error}")
