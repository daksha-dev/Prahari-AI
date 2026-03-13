# Terminal 1: uvicorn server:app --reload
# Terminal 2: streamlit run dashboard.py
# Terminal 3: python simulate_live.py  (or: python simulate_live.py --device 10.0.2.1)

import math
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from anomaly_detector import DualModelDetector
from drift_detector import DriftDetector
from feature_engineer import FEATURE_NAMES
from policy_checker import PolicyChecker
from trust_engine import TrustEngine


# ── Config ────────────────────────────────────────────────────────────────────

def _load_config(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG = _load_config()
BURN_IN_WINDOWS: int = int(CONFIG.get("data", {}).get("burn_in_windows", 30))
_CHI_SQ_RECENT: int = int(
    CONFIG.get("drift", {}).get("chi_squared", {}).get("recent_windows", 10)
)


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(title="IoT Trust & Drift Server")


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict) -> None:
        dead: List[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ── Per-device state ──────────────────────────────────────────────────────────

class DeviceState:
    """All mutable state for a single device."""

    def __init__(self, config: dict) -> None:
        self.trust_engine = TrustEngine(config)
        self.dual_detector = DualModelDetector(config)
        self.drift_detector = DriftDetector(config)
        self.policy_checker = PolicyChecker(config)

        # Burn-in accumulation (fills for first BURN_IN_WINDOWS, then locked)
        self.burn_in_feature_dicts: List[dict] = []
        self.burn_in_arrays: List[np.ndarray] = []
        self.burn_in_complete: bool = False
        self.burn_in_matrix: Optional[np.ndarray] = None  # frozen after burn-in

        # Baseline sets (frozen after burn-in)
        self.baseline_ips: Set[str] = set()
        self.baseline_protocols: Set[str] = set()
        self.baseline_ports: Set[int] = set()

        # Feature history for chi-squared (last _CHI_SQ_RECENT monitoring windows)
        self.feature_history: deque = deque(maxlen=_CHI_SQ_RECENT)

        # ADWIN disagreement counter (stored on drift_detector internally)
        # Current trust score (100 during burn-in, updated during monitoring)
        self.trust_score: float = 100.0

        # Total windows received (including burn-in)
        self.window_count: int = 0


# Global device registry keyed by device_id
devices: Dict[str, DeviceState] = {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _payload_to_features(
    bytes_sent: float,
    packets: float,
    dst_ips: List[str],
    request_rate: float,
    baseline_ips: Set[str],
) -> dict:
    """Convert /ingest payload fields to the 22-feature dict."""
    total_bytes = float(bytes_sent)
    total_packets = float(packets)
    unique_ips = set(dst_ips)
    n_unique = float(len(unique_ips)) if unique_ips else 0.0
    total_flows = max(1.0, n_unique)

    packets_per_sec = float(request_rate)
    bytes_per_sec = total_bytes / 60.0
    flows_per_sec = total_flows / 60.0

    unique_dst_ips = n_unique
    if n_unique > 1:
        p = 1.0 / n_unique
        dst_ip_entropy = float(-n_unique * p * math.log2(p))
    else:
        dst_ip_entropy = 0.0

    # Port / protocol columns not available from this payload — zero-filled.
    unique_dst_ports = 0.0
    port_entropy = 0.0
    tcp_ratio = 0.0
    udp_ratio = 0.0
    icmp_ratio = 0.0
    mean_iat = 0.0
    mean_flow_duration = 0.0
    syn_ack_ratio = 0.0
    rst_rate = 0.0
    flow_symmetry = 1.0
    burstiness = 0.0

    new_dst_count = float(len(unique_ips - baseline_ips)) if baseline_ips else 0.0
    avg_payload_size = total_bytes / total_packets if total_packets > 0 else 0.0
    connection_failure_rate = 0.0

    return {
        "total_bytes":              total_bytes,
        "total_packets":            total_packets,
        "total_flows":              total_flows,
        "packets_per_sec":          packets_per_sec,
        "bytes_per_sec":            bytes_per_sec,
        "flows_per_sec":            flows_per_sec,
        "unique_dst_ips":           unique_dst_ips,
        "unique_dst_ports":         unique_dst_ports,
        "dst_ip_entropy":           dst_ip_entropy,
        "port_entropy":             port_entropy,
        "tcp_ratio":                tcp_ratio,
        "udp_ratio":                udp_ratio,
        "icmp_ratio":               icmp_ratio,
        "mean_iat":                 mean_iat,
        "mean_flow_duration":       mean_flow_duration,
        "syn_ack_ratio":            syn_ack_ratio,
        "rst_rate":                 rst_rate,
        "flow_symmetry":            flow_symmetry,
        "burstiness":               burstiness,
        "new_dst_count":            new_dst_count,
        "avg_payload_size":         avg_payload_size,
        "connection_failure_rate":  connection_failure_rate,
    }


def _features_to_array(feat_dict: dict) -> np.ndarray:
    return np.array([feat_dict.get(n, 0.0) for n in FEATURE_NAMES], dtype=float)


def _top_features(
    feat_dict: dict,
    burn_in_matrix: Optional[np.ndarray],
    n: int = 2,
) -> List[str]:
    """Return the n feature names with highest absolute z-score vs burn-in baseline."""
    if burn_in_matrix is None or burn_in_matrix.shape[0] == 0:
        return []
    means = burn_in_matrix.mean(axis=0)
    stds = burn_in_matrix.std(axis=0) + 1e-9
    feat_arr = _features_to_array(feat_dict)
    z = np.abs((feat_arr - means) / stds)
    top_idx = np.argsort(z)[::-1][:n]
    return [FEATURE_NAMES[i] for i in top_idx]


def _severity(score: float) -> str:
    if score >= 70:
        return "NORMAL"
    if score >= 50:
        return "WARNING"
    if score >= 30:
        return "HIGH"
    return "CRITICAL"


# ── Ingest payload schema ─────────────────────────────────────────────────────

class IngestPayload(BaseModel):
    device_id: str
    bytes_sent: float
    packets: float
    dst_ips: List[str]
    request_rate: float
    mode: int = 0


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/ingest")
async def ingest(payload: IngestPayload):
    device_id = payload.device_id

    if device_id not in devices:
        devices[device_id] = DeviceState(CONFIG)

    state = devices[device_id]
    state.window_count += 1
    n = state.window_count

    # Build feature dict.  During burn-in, new_dst_count is computed against the
    # partially-built baseline (IPs from prior burn-in windows).
    features = _payload_to_features(
        bytes_sent=payload.bytes_sent,
        packets=payload.packets,
        dst_ips=payload.dst_ips,
        request_rate=payload.request_rate,
        baseline_ips=state.baseline_ips,
    )
    feat_arr = _features_to_array(features)

    # ── Burn-in (windows 1 … BURN_IN_WINDOWS) ────────────────────────────────
    if not state.burn_in_complete:
        state.burn_in_feature_dicts.append(features)
        state.burn_in_arrays.append(feat_arr)

        # Accumulate baseline IPs; locked after burn-in completes.
        state.baseline_ips.update(payload.dst_ips)

        if n < BURN_IN_WINDOWS:
            return {"status": "burn_in", "window": n}

        # ── Window BURN_IN_WINDOWS reached → finalise burn-in ──────────────
        burn_in_matrix = np.vstack(state.burn_in_arrays)   # (30, 22)
        state.burn_in_matrix = burn_in_matrix

        # Train Isolation Forest on burn-in feature matrix and freeze it.
        state.dual_detector.train_static(burn_in_matrix)

        # Prime Half-Space Trees so it has a reference distribution.
        state.dual_detector.prime_adaptive(state.burn_in_feature_dicts)

        # Pre-seed ADWIN and disagreement with burn-in scores (mirrors main.py).
        burn_scores = [
            state.dual_detector.score(fd) for fd in state.burn_in_feature_dicts
        ]
        for bi_if, bi_hst, bi_combined in burn_scores:
            state.drift_detector.update_disagreement(bi_if, bi_hst)
            for _ in range(3):
                state.drift_detector.update_adwin(bi_combined)

        state.burn_in_complete = True
        return {"status": "burn_in", "window": n}

    # ── Monitoring (window BURN_IN_WINDOWS + 1 onward) ────────────────────────
    state.feature_history.append(feat_arr)

    if_score, hst_score, combined_score = state.dual_detector.score(features)

    state.drift_detector.update_adwin(combined_score)

    if len(state.feature_history) >= 2:
        recent_matrix = np.vstack(list(state.feature_history))
        state.drift_detector.update_chi_squared(state.burn_in_matrix, recent_matrix)

    state.drift_detector.update_disagreement(if_score, hst_score)

    drift_meta = state.drift_detector.compute_drift_metadata()
    drift_confirmed = drift_meta["confirmed"]
    drift_factor = drift_meta["drift_factor"]

    policy_penalty, _ = state.policy_checker.check_policies(
        features,
        baseline_ips=state.baseline_ips,
        config=CONFIG,
        baseline_protocols=state.baseline_protocols,
        baseline_ports=state.baseline_ports,
    )

    trust_score = state.trust_engine.update(
        anomaly_score=combined_score,
        drift_factor=drift_factor,
        drift_confirmed=drift_confirmed,
        policy_penalty=float(policy_penalty),
    )
    state.trust_score = trust_score

    # HST adapts after scoring (suppressed when trust < 50 to prevent poisoning).
    state.dual_detector.update_adaptive(
        features, trust_score=trust_score, device_id=device_id
    )

    top_feats = _top_features(features, state.burn_in_matrix)

    result = {
        "device_id":      device_id,
        "trust_score":    round(trust_score, 1),
        "anomaly_score":  round(combined_score, 4),
        "drift_confirmed": drift_confirmed,
        "signals": {
            "adwin":    drift_meta["adwin_signal"],
            "chi2":     drift_meta["chi_squared_signal"],
            "disagree": drift_meta["disagreement_signal"],
        },
        "top_features": top_feats,
        "severity":     _severity(trust_score),
    }

    await manager.broadcast(result)
    return result


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # Keep the connection alive; server pushes data via broadcast().
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/status")
async def status():
    """Return current trust scores and severity for all post-burn-in devices."""
    return {
        device_id: {
            "trust_score": round(state.trust_score, 1),
            "severity":    _severity(state.trust_score),
        }
        for device_id, state in devices.items()
        if state.burn_in_complete
    }
