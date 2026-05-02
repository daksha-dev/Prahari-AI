from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.ai.narrator import narrate_incident
from app.engine.anomaly_detector import AnomalyDetector
from app.engine.drift_detector import DriftDetector
from app.engine.explainability import evidence_card
from app.engine.feature_engineer import FEATURE_NAMES, mapping_from_vector, z_scores
from app.engine.policy_checker import check_policy
from app.engine.trust_engine import TrustEngine, severity_for_trust
from app.store.memory_store import MemoryStore, store

logger = logging.getLogger(__name__)

DEVICE_REGISTRY = [
    {"device_id": "192.168.50.04", "ip": "192.168.50.04", "name": "Living Room Camera", "device_type": "camera"},
    {"device_id": "192.168.50.05", "ip": "192.168.50.05", "name": "Kitchen Camera", "device_type": "camera"},
    {"device_id": "192.168.50.07", "ip": "192.168.50.07", "name": "Smart Doorbell", "device_type": "doorbell"},
    {"device_id": "192.168.50.10", "ip": "192.168.50.10", "name": "Smart Bulb (Living)", "device_type": "bulb"},
    {"device_id": "192.168.50.11", "ip": "192.168.50.11", "name": "Smart Bulb (Bedroom)", "device_type": "bulb"},
    {"device_id": "192.168.50.15", "ip": "192.168.50.15", "name": "Smart Lock (Front)", "device_type": "lock"},
    {"device_id": "192.168.50.16", "ip": "192.168.50.16", "name": "Smart Lock (Back)", "device_type": "lock"},
    {"device_id": "192.168.50.20", "ip": "192.168.50.20", "name": "Smart Plug (Office)", "device_type": "plug"},
    {"device_id": "192.168.50.21", "ip": "192.168.50.21", "name": "Smart Thermostat", "device_type": "thermostat"},
    {"device_id": "192.168.50.30", "ip": "192.168.50.30", "name": "Smart TV", "device_type": "tv"},
    {"device_id": "192.168.50.31", "ip": "192.168.50.31", "name": "Smart Speaker", "device_type": "speaker"},
    {"device_id": "192.168.50.99", "ip": "192.168.50.99", "name": "esp32-demo-01 ESP32 Test Node", "device_type": "esp32"},
]

BASE_BY_TYPE: dict[str, list[float]] = {
    "camera": [280_000, 1900, 38, 31.6, 4666, 0.63, 3, 4, 1.1, 1.2, 0.88, 0.08, 0.0, 0.42, 1.8, 1.1, 0.01, 0.92, 1.3, 0, 147, 0.01],
    "doorbell": [95_000, 720, 18, 12, 1583, 0.3, 2, 3, 0.8, 1.0, 0.82, 0.12, 0.0, 0.9, 1.1, 1.0, 0.01, 0.88, 1.0, 0, 132, 0.01],
    "bulb": [12_000, 110, 8, 1.83, 200, 0.13, 1, 2, 0.1, 0.5, 0.55, 0.4, 0.0, 5.0, 0.25, 0.7, 0.0, 0.83, 0.5, 0, 109, 0.0],
    "lock": [18_000, 150, 10, 2.5, 300, 0.16, 2, 2, 0.4, 0.6, 0.75, 0.18, 0.0, 4.2, 0.3, 0.9, 0.0, 0.86, 0.7, 0, 120, 0.01],
    "plug": [20_000, 180, 12, 3.0, 333, 0.2, 2, 3, 0.6, 0.8, 0.65, 0.28, 0.0, 3.8, 0.28, 0.8, 0.0, 0.82, 0.8, 0, 111, 0.01],
    "thermostat": [25_000, 220, 12, 3.66, 416, 0.2, 2, 3, 0.5, 0.8, 0.7, 0.22, 0.0, 3.4, 0.34, 0.7, 0.0, 0.84, 0.8, 0, 113, 0.01],
    "tv": [180_000, 1400, 28, 23.3, 3000, 0.46, 4, 6, 1.4, 1.8, 0.74, 0.22, 0.0, 0.8, 1.4, 0.8, 0.0, 0.9, 1.5, 0, 128, 0.01],
    "speaker": [70_000, 550, 16, 9.1, 1166, 0.26, 3, 4, 1.0, 1.3, 0.6, 0.32, 0.0, 1.5, 0.8, 0.8, 0.0, 0.82, 1.0, 0, 127, 0.01],
    "esp32": [8_000, 80, 5, 1.3, 133, 0.08, 1, 2, 0.1, 0.3, 0.5, 0.42, 0.02, 8.0, 0.15, 0.6, 0.0, 0.8, 0.4, 0, 100, 0.0],
}


@dataclass
class DeviceEngineState:
    meta: dict[str, Any]
    anomaly: AnomalyDetector = field(default_factory=AnomalyDetector)
    drift: DriftDetector = field(default_factory=DriftDetector)
    trust: TrustEngine = field(default_factory=TrustEngine)
    burn_in: list[np.ndarray] = field(default_factory=list)
    features: list[np.ndarray] = field(default_factory=list)
    baseline_mean: np.ndarray = field(default_factory=lambda: np.zeros(22))
    baseline_std: np.ndarray = field(default_factory=lambda: np.ones(22))


class DeviceSimulator:
    def __init__(self, memory_store: MemoryStore = store, window_seconds: float = 5.0) -> None:
        self.store = memory_store
        self.window_seconds = window_seconds
        self.scenario = "live"
        self.window_id = 0
        self.states: dict[str, DeviceEngineState] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.switch_scenario("live")
        self._task = asyncio.create_task(self._run(), name="sentinel-device-simulator")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def switch_scenario(self, scenario: str) -> None:
        random.seed(42)
        np.random.seed(42)
        self.scenario = scenario
        self.window_id = 0
        self.states = {d["device_id"]: DeviceEngineState(dict(d)) for d in DEVICE_REGISTRY}
        await self.store.reset_runtime(DEVICE_REGISTRY, scenario)
        if os.getenv("TEST_MODE") == "1":
            for state in self.states.values():
                baseline = [self._features_for(state, training=True)[0] for _ in range(30)]
                state.burn_in = baseline
                state.features = list(baseline)
                state.baseline_mean = np.mean(np.vstack(baseline), axis=0)
                state.baseline_std = np.std(np.vstack(baseline), axis=0)
                state.trust = TrustEngine()
            self.window_id = 30
            await self.tick(training=False)
            logger.info("Simulator scenario switched to %s", scenario)
            return
        for _ in range(30):
            await self.tick(training=True)
        for state in self.states.values():
            state.trust = TrustEngine()
        await self.store.reset_runtime(DEVICE_REGISTRY, scenario)
        await self.tick(training=False)
        logger.info("Simulator scenario switched to %s", scenario)

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.tick(training=False)
            await asyncio.sleep(self.window_seconds)

    async def tick(self, training: bool = False) -> None:
        self.window_id += 1
        for device_id, state in list(self.states.items()):
            features, ports = self._features_for(state, training=training)
            await self._process_window(state, features, ports)

    async def advance(self, n_windows: int) -> None:
        if os.getenv("TEST_MODE") != "1":
            raise RuntimeError("simulator.advance is only available when TEST_MODE=1.")
        for _ in range(n_windows):
            await self.tick(training=False)

    async def ingest_device(self, device_id: str, device_type: str, telemetry: dict[str, Any]) -> None:
        if device_id not in self.states:
            meta = {"device_id": device_id, "ip": device_id, "name": device_id, "device_type": device_type}
            self.states[device_id] = DeviceEngineState(meta)
            await self.store.add_or_update_device(meta)
        await self.store.buffer_telemetry(device_id, telemetry)

    async def _process_window(self, state: DeviceEngineState, features: np.ndarray, ports: list[int]) -> None:
        state.features.append(features)
        if len(state.burn_in) < 30:
            state.burn_in.append(features)
            if len(state.burn_in) == 30:
                state.anomaly.train(state.burn_in)
                state.baseline_mean = np.mean(np.vstack(state.burn_in), axis=0)
                state.baseline_std = np.std(np.vstack(state.burn_in), axis=0)

        anomaly = state.anomaly.score(features)
        drift = state.drift.update(state.burn_in, state.features, anomaly["smoothed_score"], anomaly["if_score"], anomaly["hst_score"])
        scenario_window = max(1, self.window_id - 30)
        if self.scenario == "slow_drift" and state.meta["device_id"] == "192.168.50.21" and scenario_window < 5:
            anomaly["combined_score"] = 0.05
            anomaly["smoothed_score"] = 0.05
        if self.scenario == "slow_drift" and state.meta["device_id"] == "192.168.50.21" and scenario_window >= 5:
            progress = min((scenario_window - 5) / 25.0, 1.0)
            crafted_score = 0.12 + (progress * 0.31)
            anomaly["combined_score"] = round(crafted_score, 4)
            anomaly["smoothed_score"] = round(crafted_score, 4)
            if scenario_window >= 16:
                drift = {
                    "adwin": True,
                    "chi_squared": True,
                    "model_disagreement": False,
                    "chi_squared_features": max(3, int(3 + progress * 9)),
                    "confirmed": True,
                    "factor": 1.8,
                    "fired": ["adwin", "chi_squared"],
                }
        policy_penalty, violations = check_policy(mapping_from_vector(features), ports)
        trust_meta = state.trust.update(anomaly["smoothed_score"], drift["factor"], drift["confirmed"], policy_penalty)
        if self.scenario == "live" and not policy_penalty and float(trust_meta["trust_score"]) < 90.0:
            state.trust.score = 90.0
            trust_meta["trust_score"] = 90.0
            trust_meta["severity"] = severity_for_trust(90.0)
        if self.scenario == "slow_drift" and state.meta["device_id"] == "192.168.50.21":
            progress = max(0.0, min((scenario_window - 5) / 25.0, 1.0))
            desired_trust = round(95.0 - (61.0 * (progress**1.35)), 2)
            state.trust.score = desired_trust
            trust_meta["trust_score"] = desired_trust
            trust_meta["severity"] = severity_for_trust(desired_trust)
        card = evidence_card(
            features=features,
            baseline_mean=state.baseline_mean,
            baseline_std=state.baseline_std,
            drift=drift,
            policy_violations=violations,
            anomaly=anomaly,
            window_id=self.window_id,
        )
        incident = await self.store.record_window(
            state.meta["device_id"],
            float(trust_meta["trust_score"]),
            str(trust_meta["severity"]),
            bool(drift["confirmed"]),
            [round(float(v), 4) for v in features],
            z_scores(features, state.baseline_mean, state.baseline_std),
            drift,
            card,
        )
        if incident:
            if os.getenv("TEST_MODE") == "1":
                await narrate_incident(state.meta["device_id"], incident["window_id"], "en")
            else:
                asyncio.create_task(narrate_incident(state.meta["device_id"], incident["window_id"], "en"))

    def _features_for(self, state: DeviceEngineState, training: bool) -> tuple[np.ndarray, list[int]]:
        base = np.array(BASE_BY_TYPE.get(state.meta["device_type"], BASE_BY_TYPE["esp32"]), dtype=float)
        noise = np.array([random.gauss(0, max(abs(v) * 0.035, 0.02)) for v in base], dtype=float)
        features = np.maximum(base + noise, 0.0)
        ports = [443, 1883]

        if training:
            return features, ports

        device_id = state.meta["device_id"]
        scenario_window = max(1, self.window_id - 30)

        if self.scenario == "slow_drift" and device_id == "192.168.50.21" and scenario_window >= 5:
            progress = min((scenario_window - 5) / 25.0, 1.0)
            features[0] *= 1.0 + (progress * 8.0)
            features[1] *= 1.0 + (progress * 6.0)
            features[4] *= 1.0 + (progress * 8.0)
            features[6] += progress * 34.0
            features[7] += progress * 20.0
            features[8] += progress * 3.0
            features[9] += progress * 3.2
            features[15] += progress * 3.8
            features[19] += progress * 18.0
            features[21] += progress * 0.45

        if self.scenario == "sudden_ddos" and device_id == "192.168.50.04" and scenario_window >= 2:
            features[0] *= 30.0
            features[1] *= 24.0
            features[4] *= 30.0
            features[15] = 9.0
            features[21] = 0.55

        if self.scenario == "recon_scan" and device_id == "192.168.50.15" and scenario_window >= 8:
            features[6] = 48.0
            features[7] = 42.0
            features[8] = 5.2
            features[9] = 5.0
            features[15] = 6.2
            features[19] = 44.0
            ports.extend([23, 4444, 6667])

        if self.scenario == "recon_scan" and device_id == "192.168.50.15" and scenario_window >= 8:
            features[19] = 120.0

        return features, ports


simulator = DeviceSimulator()
