from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

os.environ["TEST_MODE"] = "1"
os.environ.setdefault("SIMULATOR_ENABLED", "false")

from app.api import chat as chat_module
from app.main import app
from app.simulator.device_simulator import simulator


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
async def fresh_state() -> None:
    await simulator.switch_scenario("live")


@pytest.fixture
def advance_simulator():
    async def advance(n_windows: int) -> None:
        await simulator.advance(n_windows)

    return advance


class FakeSarvamClient:
    def __init__(self, scripts: list[list[dict[str, Any]]] | None = None, error: Exception | None = None) -> None:
        self.scripts = scripts or [[{"choices": [{"delta": {"content": "Mock Sentinel response"}}]}]]
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, Any]], tools=None, language: str = "en", stream: bool = True):
        self.calls.append({"messages": messages, "tools": tools, "language": language, "stream": stream})
        if self.error:
            raise self.error
        script = self.scripts.pop(0) if self.scripts else [{"choices": [{"delta": {"content": "Done"}}]}]
        for event in script:
            yield event


@pytest.fixture
def mock_sarvam(monkeypatch):
    fake = FakeSarvamClient()
    monkeypatch.setattr(chat_module, "sarvam_client", fake)
    return fake


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.split("\n\n"):
        line = next((part for part in block.splitlines() if part.startswith("data: ")), None)
        if line:
            events.append(json.loads(line[6:]))
    return events
