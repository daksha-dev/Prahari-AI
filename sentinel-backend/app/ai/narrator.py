from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.sarvam_client import SarvamError, SarvamUnavailable, sarvam_client
from app.ai.stream_parser import content_from_choice, safe_choices, strip_reasoning
from app.store.memory_store import store

logger = logging.getLogger(__name__)

NARRATION_PROMPT = (
    "You are Sentinel's incident narrator. Given the structured evidence below for an IoT device that just dropped below trust threshold 70, "
    "write a concise 4-6 sentence incident summary for a security analyst. Lead with what the device is and what just changed. "
    "Then explain which behaviors deviated, by how much, and what attack pattern it resembles. End with one sentence on what action to consider. "
    "No bullet points, no headers, just plain prose. Do not use technical jargon without translating it inline.\n\n"
    "Evidence: {evidence_json}"
)

LANGUAGE_INSTRUCTIONS = {
    "en": "User is conversing in English. Respond in English.",
    "hi": "उपयोगकर्ता हिंदी में बात कर रहे हैं। कृपया हिंदी में उत्तर दें।",
    "kn": "ಬಳಕೆದಾರರು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡುತ್ತಿದ್ದಾರೆ. ದಯವಿಟ್ಟು ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರಿಸಿ.",
    "ta": "பயனர் தமிழில் பேசுகிறார். தயவுசெய்து தமிழில் பதிலளிக்கவும்.",
    "te": "వినియోగదారు తెలుగులో మాట్లాడుతున్నారు. దయచేసి తెలుగులో సమాధానం ఇవ్వండి.",
}

FALLBACK_NARRATION = (
    "Sentinel detected a trust drop below 70 for this IoT device. "
    "The latest evidence shows behavior moving away from the device baseline, which may indicate compromise or misuse. "
    "Review the evidence card, confirm whether this behavior is expected, and consider isolating the device if the deviation continues."
)


async def narrate_device(device_id: str, language: str = "en") -> str:
    incident = await store.get_latest_incident(device_id)
    if incident:
        return await narrate_incident(device_id, incident["window_id"], language)

    evidence = await store.read_evidence_card(device_id)
    if not evidence:
        return FALLBACK_NARRATION
    window_id = int(evidence.get("window_id", 0))
    return await narrate_incident(device_id, window_id, language)


async def narrate_incident(device_id: str, window_id: int, language: str = "en") -> str:
    cached = store.ai_summary_cache.get((device_id, window_id, language))
    if cached:
        return cached

    evidence = await store.read_evidence_card(device_id)
    device = await store.get_device(device_id)
    if not evidence or not device:
        await store.cache_narration(device_id, window_id, language, FALLBACK_NARRATION)
        return FALLBACK_NARRATION

    payload: dict[str, Any] = {
        "device": device["device"],
        "current_trust": device["current_trust"],
        "severity": device["severity"],
        "evidence": evidence,
    }
    prompt = (
        NARRATION_PROMPT.format(evidence_json=json.dumps(payload, ensure_ascii=False, default=str))
        + "\n\n"
        + LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])
    )
    try:
        chunks = []
        async for event in sarvam_client.chat([{"role": "user", "content": prompt}], tools=None, language=language, stream=True):
            for choice in safe_choices(event):
                content = content_from_choice(choice)
                if content:
                    chunks.append(content)
        summary = strip_reasoning("".join(chunks)) or FALLBACK_NARRATION
    except (SarvamUnavailable, SarvamError, IndexError, TypeError, KeyError, AttributeError, ValueError):
        logger.exception("Sarvam narration failed")
        summary = FALLBACK_NARRATION

    await store.cache_narration(device_id, window_id, language, summary)
    return summary
