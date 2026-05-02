from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import IngestRequest
from app.simulator.device_simulator import simulator

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest")
async def ingest(payload: IngestRequest) -> dict:
    await simulator.ingest_device(payload.device_id, payload.device_type, payload.telemetry.model_dump())
    return {"ok": True, "device_id": payload.device_id}
