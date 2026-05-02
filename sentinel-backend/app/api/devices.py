from __future__ import annotations

from app.models.schemas import Language
from fastapi import APIRouter, HTTPException, Query

from app.ai.narrator import narrate_device
from app.store.memory_store import store

router = APIRouter(prefix="/api", tags=["devices"])


@router.get("/devices")
async def list_devices() -> list[dict]:
    return await store.list_devices()


@router.get("/devices/{device_id}")
async def get_device(device_id: str, language: Language | None = Query(default=None)) -> dict:
    device = await store.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if language:
        device["narration"] = await narrate_device(device_id, language)
    return device


@router.get("/devices/{device_id}/evidence")
async def get_device_evidence(device_id: str) -> dict:
    evidence = await store.read_evidence_card(device_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return evidence


@router.post("/devices/{device_id}/narrate")
async def narrate(device_id: str, language: Language = Query(default="en")) -> dict:
    device = await store.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    narration = await narrate_device(device_id, language)
    return {"device_id": device_id, "language": language, "narration": narration}


@router.get("/network-summary")
async def network_summary() -> dict:
    return await store.network_summary()
