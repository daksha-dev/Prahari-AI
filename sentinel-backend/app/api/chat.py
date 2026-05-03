from __future__ import annotations

import json
import logging
import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.ai.sarvam_client import SarvamError, SarvamUnavailable, sarvam_client
from app.ai.stream_parser import content_from_choice, safe_choices, strip_reasoning
from app.ai.system_prompts import system_prompt
from app.ai.tools import TOOL_SCHEMAS, compact_json, dispatch_tool
from app.models.schemas import ChatRequest
from app.store.memory_store import store

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
            tools_for_turn = TOOL_SCHEMAS if _should_use_tools(request.messages[-1].content if request.messages else "") else None
            for _ in range(5):
                assistant = await _collect_assistant(messages, tools_for_turn, request.language)
                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    content = strip_reasoning(assistant.get("content") or "")
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
            if tools_for_turn and _tool_calling_unsupported(exc):
                logger.warning("Sarvam model does not support native tool schemas; using local tool planner")
                content = await _answer_with_local_tool_plan(messages, request.messages[-1].content if request.messages else "", request.language, queue)
                for token in _tokenize(content):
                    await queue.put(sse_event({"type": "token", "content": token}))
                await queue.put(sse_event({"type": "done"}))
                logger.info("Chat output=%s", content)
                return
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


async def _collect_assistant(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, language: str = "en") -> dict[str, Any]:
    content_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    final_message: dict[str, Any] | None = None
    async for event in sarvam_client.chat(messages, tools=tools, language=language, stream=True):
        choices = safe_choices(event)
        if not choices:
            continue
        choice = choices[0]
        message = choice.get("message")
        if isinstance(message, dict):
            final_message = message
        delta = choice.get("delta") or {}
        content = content_from_choice(choice)
        if content:
            content_parts.append(content)
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


def _should_use_tools(prompt: str) -> bool:
    normalized = " ".join(prompt.lower().strip().split())
    if not normalized:
        return False
    trivial = {
        "hi",
        "hello",
        "hey",
        "namaste",
        "say hello",
        "say hello in one word",
    }
    if normalized in trivial:
        return False
    return True


def _tool_calling_unsupported(exc: Exception) -> bool:
    return "tool calling is not supported" in str(exc).lower()


async def _answer_with_local_tool_plan(
    messages: list[dict[str, Any]],
    prompt: str,
    language: str,
    queue: asyncio.Queue[str | None],
) -> str:
    gathered: list[dict[str, Any]] = []
    for name, args in await _local_tool_plan(prompt):
        logger.info("Local tool call name=%s args=%s", name, args)
        await queue.put(sse_event({"type": "tool_call", "name": name, "args": args}))
        result = await dispatch_tool(name, args)
        gathered.append({"name": name, "args": args, "result": result})
        snippet = compact_json(result)
        await queue.put(sse_event({"type": "tool_result", "name": name, "snippet": snippet}))

    context = compact_json(gathered, 20000)
    messages.append(
        {
            "role": "user",
            "content": (
                "Native Sarvam tool calling was unavailable, so the backend already gathered this tool context. "
                "Answer the user's last question using only this JSON context. Keep the answer concise and do not mention implementation details.\n\n"
                f"{context}"
            ),
        }
    )
    try:
        assistant = await _collect_assistant(messages, None, language)
        content = strip_reasoning(assistant.get("content") or "")
    except (SarvamUnavailable, SarvamError, IndexError, TypeError, KeyError, AttributeError, ValueError):
        logger.exception("Sarvam no-tool fallback answer failed")
        content = ""
    return content or _deterministic_tool_answer(prompt, gathered)


async def _local_tool_plan(prompt: str) -> list[tuple[str, dict[str, Any]]]:
    text = prompt.lower()
    if "what should i worry" in text or "worry about" in text:
        flagged = await dispatch_tool("list_flagged_devices", {"threshold": 70, "limit": 5})
        calls: list[tuple[str, dict[str, Any]]] = [
            ("get_recent_activity", {"minutes": 10}),
            ("list_flagged_devices", {"threshold": 70, "limit": 5}),
        ]
        if isinstance(flagged, list) and flagged:
            worst = sorted(flagged, key=lambda item: item.get("current_trust", 100))[0]
            calls.append(("explain_drift", {"device_id": worst["device_id"]}))
        return calls
    if "happening" in text or "network" in text or "going on" in text:
        return [("get_network_summary", {}), ("get_recent_activity", {"minutes": 10})]
    if "why" in text or "flagged" in text or "same pattern" in text:
        device_id = await _resolve_device_id(text)
        if device_id:
            calls = [("explain_drift", {"device_id": device_id})]
            if "same pattern" in text or "anything else" in text or "other" in text:
                compare_ids = await _comparison_ids(device_id)
                if len(compare_ids) >= 2:
                    calls.append(("compare_devices", {"device_ids": compare_ids}))
            return calls
    return [("get_network_summary", {}), ("get_recent_activity", {"minutes": 10})]


async def _resolve_device_id(text: str) -> str | None:
    for device in await store.list_devices():
        candidates = [device.get("device_id", ""), device.get("ip", ""), device.get("name", ""), device.get("device_type", "")]
        if any(str(candidate).lower() in text for candidate in candidates if candidate):
            return device["device_id"]
    return None


async def _comparison_ids(device_id: str) -> list[str]:
    target = await store.get_device(device_id)
    if not target:
        return [device_id]
    target_type = target["device"].get("device_type")
    peers = [device["device_id"] for device in await store.list_devices() if device["device_id"] != device_id and device.get("device_type") == target_type]
    return [device_id, *peers[:4]]


def _deterministic_tool_answer(prompt: str, gathered: list[dict[str, Any]]) -> str:
    prompt_text = prompt.lower()
    results = {item["name"]: item.get("result") for item in gathered}
    recent = results.get("get_recent_activity") if isinstance(results.get("get_recent_activity"), dict) else {}
    summary = results.get("get_network_summary") if isinstance(results.get("get_network_summary"), dict) else {}
    flagged = results.get("list_flagged_devices") if isinstance(results.get("list_flagged_devices"), list) else []
    changes = recent.get("score_changes", []) if isinstance(recent, dict) else []
    alerts = recent.get("alert_timeline", []) if isinstance(recent, dict) else []

    if "unusual" in prompt_text or "last hour" in prompt_text or "what should i worry" in prompt_text or "worry about" in prompt_text:
        if alerts:
            first = alerts[0]
            return (
                f"I checked recent activity and found {len(alerts)} alert event(s). "
                f"The first notable event is {first.get('device_id')} at {first.get('timestamp')}, with severity {first.get('severity')}. "
                f"Dominant attack pattern is {recent.get('dominant_attack_pattern', 'unknown')}. "
                "Review that device first, then compare peers if the pattern repeats."
            )
        if changes:
            top = changes[0]
            return (
                "I checked recent activity and did not find active alert events in the selected window. "
                f"The largest trust movement is {top.get('name', top.get('device_id'))}, changing from {top.get('from')} to {top.get('to')} "
                f"({top.get('delta')} points). "
                "That is the best candidate for follow-up, but it is not currently flagged below the trust threshold."
            )
        return "I checked recent activity and did not find alerts or meaningful trust-score movement in the selected window."

    if flagged:
        worst = flagged[0]
        return (
            f"The device needing attention first is {worst.get('name', worst.get('device_id'))}, "
            f"currently at trust score {worst.get('current_trust')} with severity {worst.get('severity')}. "
            "Use the evidence panel or ask why it was flagged for the detailed drift explanation."
        )

    if summary:
        return (
            f"The network currently has {summary.get('healthy_count', 0)} of {summary.get('total_devices', 0)} devices healthy, "
            f"with mean trust {summary.get('mean_trust')}. "
            f"Drift is confirmed on {summary.get('drift_confirmed_count', 0)} device(s)."
        )

    return "I checked the available evidence, but no narrative answer was returned. Please retry the question or ask about one device."


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
