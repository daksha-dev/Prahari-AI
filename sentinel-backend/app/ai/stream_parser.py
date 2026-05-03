from __future__ import annotations

import re
from typing import Any


def safe_choices(event: dict[str, Any]) -> list[dict[str, Any]]:
    choices = event.get("choices")
    if not isinstance(choices, list):
        return []
    return [choice for choice in choices if isinstance(choice, dict)]


def content_from_choice(choice: dict[str, Any]) -> str:
    parts: list[str] = []
    delta = choice.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        parts.append(delta["content"])
    message = choice.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        parts.append(message["content"])
    return "".join(parts)


def strip_reasoning(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
