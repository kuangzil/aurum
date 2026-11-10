import asyncio
import json

import httpx
import pytest

from backend.a2a_transport.client import ValidationClient, ValidationUnavailable
from backend.config import Settings
from backend.llm import LLMError, OpenAICompatibleLLM
from backend.research_agent.schemas import ResearchPlan
from backend.tests.test_agents import fixture_research


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


async def test_a2a_discovery_obeys_total_deadline(monkeypatch):
    async def stalled(request):
        await asyncio.sleep(10)
        return httpx.Response(200, json={})

    mock_http(monkeypatch, stalled)
    events = []

    async def report(event):
        events.append(event)

    with pytest.raises(ValidationUnavailable, match="timed out"):
        await ValidationClient("http://validator.test", 0.02).validate(await fixture_research(), report)
    assert events[-1].stage == "failed"


async def test_invalid_agent_card_is_meaningful_failure(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"name": "Broken"}))
    with pytest.raises(ValidationUnavailable, match="invalid A2A response"):
        await ValidationClient("http://validator.test", 1).validate(await fixture_research())


async def test_compatible_llm_uses_json_and_validates_output(monkeypatch):
    def provider(request):
        body = json.loads(request.content)
        assert request.url == "https://provider.test/v1/chat/completions"
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        assert "JSON" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "objective": "Test gold momentum", "tasks": ["Specify lagged signal"],
            "hypothesis": "A lagged signal improves net performance relative to buy-and-hold.",
            "methodology": "Out-of-sample test with costs.",
        })}}]})

    mock_http(monkeypatch, provider)
    settings = Settings(_env_file=None, llm_mode="openai", openai_api_key="test-only", openai_model="test-model", openai_base_url="https://provider.test/v1")
    result = await OpenAICompatibleLLM(settings).generate(ResearchPlan, "Plan research.", {"query": "gold momentum"})
    assert result.objective == "Test gold momentum"


@pytest.mark.parametrize("status,body", [(401, {"error": "secret provider detail"}), (200, {"choices": []}), (200, {"choices": [{"message": {"content": "not JSON"}}]})])
async def test_llm_failure_is_not_silently_mocked_or_leaked(monkeypatch, status, body):
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=body))
    settings = Settings(_env_file=None, llm_mode="openai", openai_api_key="test-only", openai_model="test-model")
    with pytest.raises(LLMError, match="invalid structured output") as caught:
        await OpenAICompatibleLLM(settings).generate(ResearchPlan, "", {})
    assert "secret" not in str(caught.value)
