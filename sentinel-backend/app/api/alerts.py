from __future__ import annotations

from fastapi import APIRouter

from app.ai.narrator import narrate_incident
from app.store.memory_store import store

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts")
async def alerts() -> list[dict]:
    incidents = await store.alerts()
    for incident in incidents:
        if not incident.get("ai_summary"):
            incident["ai_summary"] = await narrate_incident(incident["device_id"], incident["window_id"], "en")
    return incidents
