from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
from sarvamai import SarvamAI

from app.config import ENV_FILE, get_settings

logger = logging.getLogger(__name__)


class SarvamError(RuntimeError):
    pass


class SarvamUnavailable(SarvamError):
    pass


class SarvamClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

    @property
    def api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        return os.environ.get("SARVAM_API_KEY") or get_settings().sarvam_api_key

    @property
    def model(self) -> str:
        return self._model if self._model is not None else get_settings().sarvam_model

    @property
    def base_url(self) -> str:
        return self._base_url if self._base_url is not None else get_settings().sarvam_base_url

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        language: str = "en",
        stream: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.api_key:
            raise SarvamUnavailable(
                f"SARVAM_API_KEY is empty. "
                f"Resolved env file: {ENV_FILE}. "
                f"File exists: {ENV_FILE.exists()}. "
                f"File size: {ENV_FILE.stat().st_size if ENV_FILE.exists() else 'N/A'} bytes. "
                f"Restart uvicorn after editing .env."
            )
        try:
            async for event in self._chat_with_sdk(messages, tools, stream):
                yield event
        except TypeError as exc:
            if tools:
                logger.exception("Sarvam SDK rejected chat call; trying OpenAI-compatible HTTP fallback")
                async for event in self._chat_with_httpx(messages, tools, stream):
                    yield event
            else:
                logger.exception("Sarvam SDK call failed")
                raise SarvamError(f"Sarvam SDK call failed: {exc}") from exc
        except Exception as exc:
            logger.exception("Sarvam SDK call failed")
            raise SarvamError(f"Sarvam SDK call failed: {exc}") from exc

    async def _chat_with_sdk(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> AsyncIterator[dict[str, Any]]:
        def call() -> Any:
            logger.info("Creating SarvamAI client with key prefix: %s", self.api_key[:4] if self.api_key else "EMPTY")
            client = SarvamAI(api_subscription_key=self.api_key)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.3,
                "top_p": 1,
                "max_tokens": 2000,
                "stream": stream,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            return client.chat.completions(**kwargs)

        response = await asyncio.to_thread(call)
        if stream:
            events = await asyncio.to_thread(lambda: [self._to_dict(chunk) for chunk in response])
            for event in events:
                yield event
        else:
            yield self._to_dict(response)

    async def _chat_with_httpx(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> AsyncIterator[dict[str, Any]]:
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools or [],
            "tool_choice": "auto" if tools else "none",
            "stream": stream,
            "temperature": 0.3,
            "top_p": 1,
            "max_tokens": 2000,
        }
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                if stream:
                    async with client.stream("POST", url, headers=headers, json=body) as response:
                        if response.status_code >= 400:
                            detail = (await response.aread()).decode(errors="replace")
                            raise SarvamError(f"Sarvam HTTP fallback returned HTTP {response.status_code}: {detail}")
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            payload = line.removeprefix("data:").strip()
                            if payload == "[DONE]":
                                break
                            if payload:
                                yield json.loads(payload)
                else:
                    response = await client.post(url, headers=headers, json=body)
                    if response.status_code >= 400:
                        raise SarvamError(f"Sarvam HTTP fallback returned HTTP {response.status_code}: {response.text}")
                    yield response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.exception("Sarvam HTTP fallback failed")
            raise SarvamError(f"Sarvam HTTP fallback failed: {exc}") from exc

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump(exclude_none=True)
        if isinstance(value, dict):
            return value
        return json.loads(json.dumps(value, default=lambda item: getattr(item, "__dict__", str(item))))


def chunk_text_as_openai_events(text: str, chunk_words: int = 5) -> Iterator[dict[str, Any]]:
    words = text.split()
    for index in range(0, len(words), chunk_words):
        content = " ".join(words[index : index + chunk_words])
        if index + chunk_words < len(words):
            content += " "
        yield {"choices": [{"delta": {"content": content}}]}


sarvam_client = SarvamClient()
