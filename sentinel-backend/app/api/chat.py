from __future__ import annotations

import json
import logging
import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.ai.sarvam_client import SarvamError, SarvamUnavailable, sarvam_client
from app.ai.system_prompts import system_prompt
from app.ai.tools import TOOL_SCHEMAS, compact_json, dispatch_tool
from app.models.schemas import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    async def produce(queue: asyncio.Queue[str | None]):
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(request.language)}]
        messages.extend([m.model_dump() for m in request.messages])
        logger.info("Chat turn user=%s", request.messages[-1].content if request.messages else "")

        try:
            for _ in range(5):
                assistant = await _collect_assistant(messages, TOOL_SCHEMAS, request.language)
                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    content = assistant.get("content") or ""
                    for token in _tokenize(content):
                        await queue.put(sse_event({"type": "token", "content": token}))
                    await queue.put(sse_event({"type": "done"}))
                    logger.info("Chat output=%s", content)
                    return

                messages.append({"role": "assistant", "content": assistant.get("content") or "", "tool_calls": tool_calls})
                for call in tool_calls:
                    function = call.get("function", {})
                    name = function.get("name", "")
                    args = _parse_args(function.get("arguments", "{}"))
                    logger.info("Tool call name=%s args=%s", name, args)
                    await queue.put(sse_event({"type": "tool_call", "name": name, "args": args}))
                    result = await dispatch_tool(name, args)
                    snippet = compact_json(result)
                    await queue.put(sse_event({"type": "tool_result", "name": name, "snippet": snippet}))
                    messages.append({"role": "tool", "tool_call_id": call.get("id", name), "name": name, "content": compact_json(result, 20000)})

            fallback = "I checked the available tools, but the tool-call loop did not settle. Please ask for one device or one action at a time."
            for token in _tokenize(fallback):
                await queue.put(sse_event({"type": "token", "content": token}))
            await queue.put(sse_event({"type": "done"}))
        except SarvamUnavailable as exc:
            logger.error("Sarvam unavailable: %s", exc, exc_info=True)
            await queue.put(sse_event({"type": "error", "class": "SarvamUnavailable", "error_class": "SarvamUnavailable", "message": str(exc)}))
            fallback = f"AI Analyst error: {str(exc)}"
            await queue.put(sse_event({"type": "token", "content": fallback}))
            await queue.put(sse_event({"type": "done"}))
        except SarvamError as exc:
            logger.exception("Sarvam chat failed")
            await queue.put(sse_event({"type": "error", "class": exc.__class__.__name__, "error_class": exc.__class__.__name__, "message": str(exc)}))
            fallback = f"AI Analyst error: {type(exc).__name__}: {str(exc)}"
            await queue.put(sse_event({"type": "token", "content": fallback}))
            await queue.put(sse_event({"type": "done"}))
        except Exception as exc:
            logger.exception("Chat error")
            await queue.put(sse_event({"type": "error", "class": exc.__class__.__name__, "error_class": exc.__class__.__name__, "message": str(exc)}))
            await queue.put(sse_event({"type": "token", "content": f"AI Analyst error: {type(exc).__name__}: {str(exc)}"}))
            await queue.put(sse_event({"type": "done"}))
        finally:
            await queue.put(None)

    async def stream():
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        task = asyncio.create_task(produce(queue))
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _collect_assistant(messages: list[dict[str, Any]], tools: list[dict[str, Any]], language: str = "en") -> dict[str, Any]:
    content_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    final_message: dict[str, Any] | None = None
    async for event in sarvam_client.chat(messages, tools=tools, language=language, stream=True):
        choice = (event.get("choices") or [{}])[0]
        message = choice.get("message")
        if message:
            final_message = message
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
        for call in delta.get("tool_calls") or []:
            index = int(call.get("index", 0))
            existing = tool_calls_by_index.setdefault(index, {"id": call.get("id", f"call_{index}"), "type": "function", "function": {"name": "", "arguments": ""}})
            if call.get("id"):
                existing["id"] = call["id"]
            function = call.get("function") or {}
            if function.get("name"):
                existing["function"]["name"] += function["name"]
            if function.get("arguments"):
                existing["function"]["arguments"] += function["arguments"]
    if final_message:
        return final_message
    return {"role": "assistant", "content": "".join(content_parts), "tool_calls": [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]}


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        logger.error("Invalid tool arguments: %s", raw)
        return {}


def _tokenize(text: str) -> list[str]:
    if not text:
        return [""]
    parts = text.split(" ")
    return [part + (" " if index < len(parts) - 1 else "") for index, part in enumerate(parts)]
