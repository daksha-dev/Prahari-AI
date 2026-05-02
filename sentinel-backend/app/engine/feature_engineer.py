from __future__ import annotations

from typing import Any

import numpy as np

FEATURE_NAMES: list[str] = [
    "total_bytes",
    "total_packets",
    "total_flows",
    "packets_per_sec",
    "bytes_per_sec",
    "flows_per_sec",
    "unique_dst_ips",
    "unique_dst_ports",
    "dst_ip_entropy",
    "port_entropy",
    "tcp_ratio",
    "udp_ratio",
    "icmp_ratio",
    "mean_iat",
    "mean_flow_duration",
    "syn_ack_ratio",
    "rst_rate",
    "flow_symmetry",
    "burstiness",
    "new_dst_count",
    "avg_payload_size",
    "connection_failure_rate",
]


def vector_from_mapping(values: dict[str, Any]) -> np.ndarray:
    return np.array([float(values.get(name, 0.0) or 0.0) for name in FEATURE_NAMES], dtype=float)


def mapping_from_vector(values: np.ndarray) -> dict[str, float]:
    arr = np.asarray(values, dtype=float).ravel()
    return {name: float(arr[index]) for index, name in enumerate(FEATURE_NAMES)}


def z_scores(values: np.ndarray, mean: np.ndarray, std: np.ndarray) -> list[float]:
    arr = np.asarray(values, dtype=float)
    safe_std = np.where(std < 1e-6, 1.0, std)
    return [float(np.clip(v, -10.0, 10.0)) for v in (arr - mean) / safe_std]
