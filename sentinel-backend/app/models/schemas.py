from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Language = Literal["en", "hi", "kn", "ta", "te"]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    language: Language = "en"


class ScenarioRequest(BaseModel):
    name: str


class TelemetryPayload(BaseModel):
    temperature_c: float | None = None
    humidity_pct: float | None = None
    uptime_s: float | None = None
    rssi: float | None = None


class IngestRequest(BaseModel):
    device_id: str
    device_type: str = "esp32"
    timestamp: str | None = None
    telemetry: TelemetryPayload = Field(default_factory=TelemetryPayload)


class DeviceSummary(BaseModel):
    device_id: str
    name: str
    ip: str
    device_type: str
    current_trust: float
    severity: str
    drift_confirmed: bool
    last_alert_time: str | None
    trust_sparkline: list[float]


class EvidenceCard(BaseModel):
    top_deviating_features: list[dict[str, Any]]
    drift_signals_fired: list[str]
    policy_violations: list[dict[str, Any]]
    raw_anomaly_score: float
    smoothed_score: float
    window_id: int
    timestamp_iso: str
