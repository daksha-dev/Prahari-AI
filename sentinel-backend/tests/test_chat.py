from __future__ import annotations

import os
from typing import Any

import pytest

from app.ai.sarvam_client import SarvamClient, SarvamUnavailable
from tests.conftest import FakeSarvamClient, parse_sse


async def test_chat_endpoint_with_mock_sarvam(client, mock_sarvam):
    response = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "language": "en"})
    events = parse_sse(response.text)
    assert response.status_code == 200
    assert any(event["type"] == "token" for event in events)
    assert not any(event["type"] == "error" for event in events)
    assert events[-1]["type"] == "done"


async def test_chat_endpoint_streams_tool_calls(client, monkeypatch):
    tool_call = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_network_summary", "arguments": "{}"},
                        }
                    ]
                }
            }
        ]
    }
    fake = FakeSarvamClient(scripts=[[tool_call], [{"choices": [{"delta": {"content": "Summary ready"}}]}]])
    from app.api import chat as chat_module

    monkeypatch.setattr(chat_module, "sarvam_client", fake)
    response = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "summarize"}], "language": "en"})
    events = parse_sse(response.text)
    assert any(event["type"] == "tool_call" and event["name"] == "get_network_summary" for event in events)
    assert any(event["type"] == "tool_result" and event["name"] == "get_network_summary" for event in events)
    assert any(event["type"] == "token" and "Summary" in event["content"] for event in events)
    assert events[-1]["type"] == "done"
    assert fake.calls[-1]["messages"][-1]["role"] == "tool"


async def test_chat_endpoint_handles_sarvam_error(client, monkeypatch):
    fake = FakeSarvamClient(error=SarvamUnavailable("boom"))
    from app.api import chat as chat_module

    monkeypatch.setattr(chat_module, "sarvam_client", fake)
    response = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "language": "en"})
    events = parse_sse(response.text)
    assert events[0]["type"] == "error"
    assert events[0]["error_class"] == "SarvamUnavailable"
    assert events[0]["message"] == "boom"
    assert any(event["type"] == "token" and "AI Analyst error: boom" in event["content"] for event in events)
    assert events[-1]["type"] == "done"


async def test_chat_multi_turn_history_preserved(client, mock_sarvam):
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
    await client.post("/api/chat", json={"messages": messages, "language": "en"})
    sent = mock_sarvam.calls[0]["messages"]
    assert [message["content"] for message in sent[-3:]] == ["first", "second", "third"]


@pytest.mark.parametrize("language,prompt_name", [("hi", "SYSTEM_PROMPT_HI"), ("kn", "SYSTEM_PROMPT_KN"), ("ta", "SYSTEM_PROMPT_TA"), ("te", "SYSTEM_PROMPT_TE")])
async def test_chat_endpoint_language_routing(client, mock_sarvam, language: str, prompt_name: str):
    import app.ai.system_prompts as prompts

    await client.post("/api/chat", json={"messages": [{"role": "user", "content": "status"}], "language": language})
    sent = mock_sarvam.calls[0]
    assert sent["language"] == language
    assert getattr(prompts, prompt_name) in sent["messages"][0]["content"]


async def test_chat_invalid_payload_returns_422(client):
    response = await client.post("/api/chat", json={"messages": [{"role": "user"}], "language": "en"})
    assert response.status_code == 422


@pytest.mark.sarvam_real
def test_chat_endpoint_real_sarvam_smoke():
    from sarvamai import SarvamAI

    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        pytest.skip("SARVAM_API_KEY not set")
    client = SarvamAI(api_subscription_key=key)
    response = client.chat.completions(
        model="sarvam-m",
        messages=[{"role": "user", "content": "say hello in one word"}],
        max_tokens=10,
    )
    assert response.choices[0].message.content


def test_config_loads_api_key(monkeypatch, tmp_path):
    from app.config import Settings, get_settings

    monkeypatch.setenv("SARVAM_API_KEY", "env-key")
    get_settings.cache_clear()
    assert get_settings().SARVAM_API_KEY == "env-key"

    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("SARVAM_API_KEY=file-key\nSARVAM_MODEL=sarvam-m\n", encoding="utf-8")
    settings = Settings(_env_file=env_file)
    assert settings.SARVAM_API_KEY == "file-key"
    assert settings.SARVAM_MODEL == "sarvam-m"

    invalid_model_env = tmp_path / ".env.invalid"
    invalid_model_env.write_text("SARVAM_API_KEY=file-key\nSARVAM_MODEL=sarvam-105b\n", encoding="utf-8")
    assert Settings(_env_file=invalid_model_env).SARVAM_MODEL == "sarvam-m"
    get_settings.cache_clear()


async def test_sarvam_client_uses_correct_model(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeCompletions:
        def __call__(self, **kwargs):
            calls.append(kwargs)
            return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeSarvamAI:
        def __init__(self, api_subscription_key: str) -> None:
            self.api_subscription_key = api_subscription_key
            self.chat = FakeChat()

    import app.ai.sarvam_client as sarvam_module

    monkeypatch.setattr(sarvam_module, "SarvamAI", FakeSarvamAI)
    client = SarvamClient(api_key="test-key", model="sarvam-m")
    events = [event async for event in client.chat([{"role": "user", "content": "hello"}], stream=True)]
    assert events
    assert calls[0]["model"] == "sarvam-m"
