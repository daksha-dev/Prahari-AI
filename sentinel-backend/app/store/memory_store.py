from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from app.engine.trust_engine import severity_for_trust


class MemoryStore:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.devices: dict[str, dict[str, Any]] = {}
        self.histories: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=60))
        self.feature_histories: dict[str, deque[list[float]]] = defaultdict(lambda: deque(maxlen=60))
        self.z_histories: dict[str, deque[list[float]]] = defaultdict(lambda: deque(maxlen=30))
        self.drift_histories: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=30))
        self.evidence: dict[str, dict[str, Any]] = {}
        self.incidents: list[dict[str, Any]] = []
        self.ai_summary_cache: dict[tuple[str, int, str], str] = {}
        self.scenario = "live"
        self.telemetry_buffers: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=60))

    async def reset_runtime(self, devices: list[dict[str, Any]], scenario: str) -> None:
        async with self.lock:
            self.scenario = scenario
            self.devices = {d["device_id"]: dict(d) for d in devices}
            self.histories.clear()
            self.feature_histories.clear()
            self.z_histories.clear()
            self.drift_histories.clear()
            self.evidence.clear()
            self.incidents.clear()
            self.ai_summary_cache.clear()

    async def add_or_update_device(self, device: dict[str, Any]) -> None:
        async with self.lock:
            current = self.devices.get(device["device_id"], {})
            current.update(device)
            current.setdefault("current_trust", 95.0)
            current.setdefault("severity", "NORMAL")
            current.setdefault("drift_confirmed", False)
            current.setdefault("last_alert_time", None)
            current.setdefault("narration", None)
            self.devices[device["device_id"]] = current

    async def record_window(
        self,
        device_id: str,
        trust: float,
        severity: str,
        drift_confirmed: bool,
        features: list[float],
        z_scores: list[float],
        drift: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any] | None:
        incident: dict[str, Any] | None = None
        async with self.lock:
            timestamp = datetime.now(timezone.utc).isoformat()
            device = self.devices[device_id]
            previous = float(device.get("current_trust", 95.0))
            device["current_trust"] = round(trust, 2)
            device["severity"] = severity
            device["drift_confirmed"] = drift_confirmed
            device["updated_at"] = timestamp
            self.histories[device_id].append({"timestamp": timestamp, "trust": round(trust, 2)})
            self.feature_histories[device_id].append(features)
            self.z_histories[device_id].append(z_scores)
            self.drift_histories[device_id].append(drift)
            self.evidence[device_id] = evidence
            if previous >= 70.0 and trust < 70.0:
                device["last_alert_time"] = timestamp
                incident = {
                    "incident_id": f"{device_id}:{evidence['window_id']}",
                    "device_id": device_id,
                    "name": device.get("name", device_id),
                    "ip": device.get("ip", device_id),
                    "severity": severity_for_trust(trust),
                    "trust": round(trust, 2),
                    "timestamp_iso": timestamp,
                    "window_id": evidence["window_id"],
                    "ai_summary": None,
                }
                self.incidents.append(incident)
        return incident

    async def buffer_telemetry(self, device_id: str, reading: dict[str, Any]) -> None:
        async with self.lock:
            self.telemetry_buffers[device_id].append(reading)

    async def list_devices(self) -> list[dict[str, Any]]:
        async with self.lock:
            return [self._summary(d) for d in self.devices.values()]

    async def get_device(self, device_id: str) -> dict[str, Any] | None:
        async with self.lock:
            device = self.devices.get(device_id)
            if not device:
                return None
            return {
                "device": dict(device),
                "current_trust": device.get("current_trust", 95.0),
                "trust_history": list(self.histories[device_id]),
                "severity": device.get("severity", "NORMAL"),
                "baseline_summary": device.get("baseline_summary", {}),
                "drift_status": list(self.drift_histories[device_id]),
                "behavioral_heatmap": list(self.z_histories[device_id]),
                "narration": device.get("narration"),
            }

    async def read_evidence_card(self, device_id: str) -> dict[str, Any] | None:
        async with self.lock:
            card = self.evidence.get(device_id)
            return dict(card) if card else None

    async def get_latest_incident(self, device_id: str) -> dict[str, Any] | None:
        async with self.lock:
            for incident in reversed(self.incidents):
                if incident["device_id"] == device_id:
                    return dict(incident)
            return None

    async def cache_narration(self, device_id: str, window_id: int, language: str, narration: str) -> None:
        async with self.lock:
            self.ai_summary_cache[(device_id, window_id, language)] = narration
            if device_id in self.devices and language == "en":
                self.devices[device_id]["narration"] = narration
            if language == "en":
                for incident in self.incidents:
                    if incident["device_id"] == device_id and incident["window_id"] == window_id:
                        incident["ai_summary"] = narration

    async def alerts(self) -> list[dict[str, Any]]:
        async with self.lock:
            alerts = sorted(self.incidents, key=lambda item: item["timestamp_iso"], reverse=True)
            for alert in alerts:
                cached = self.ai_summary_cache.get((alert["device_id"], alert["window_id"], "en"))
                if cached:
                    alert["ai_summary"] = cached
            return [dict(alert) for alert in alerts]

    async def network_summary(self) -> dict[str, Any]:
        async with self.lock:
            devices = list(self.devices.values())
            trusts = [float(d.get("current_trust", 95.0)) for d in devices]
            return {
                "total_devices": len(devices),
                "mean_trust": round(sum(trusts) / len(trusts), 2) if trusts else 0.0,
                "healthy_count": sum(1 for t in trusts if t >= 70),
                "watch_count": sum(1 for t in trusts if 50 <= t < 70),
                "at_risk_count": sum(1 for t in trusts if 35 <= t < 50),
                "critical_count": sum(1 for t in trusts if t < 35),
                "drift_confirmed_count": sum(1 for d in devices if d.get("drift_confirmed")),
            }

    def _summary(self, device: dict[str, Any]) -> dict[str, Any]:
        device_id = device["device_id"]
        return {
            "device_id": device_id,
            "name": device.get("name", device_id),
            "ip": device.get("ip", device_id),
            "device_type": device.get("device_type", "unknown"),
            "current_trust": float(device.get("current_trust", 95.0)),
            "severity": device.get("severity", "NORMAL"),
            "drift_confirmed": bool(device.get("drift_confirmed", False)),
            "last_alert_time": device.get("last_alert_time"),
            "trust_sparkline": [row["trust"] for row in list(self.histories[device_id])[-20:]],
        }


store = MemoryStore()
