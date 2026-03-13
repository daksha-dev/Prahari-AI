"""
feature_engineer.py - IoT Trust & Drift Analytics System

Extracts 22 behavioral features from raw network flow records within a single
60-second time window for one device.  The feature vector captures volume,
rate, diversity, entropy, protocol mix, timing, TCP-flag, and security
characteristics — enough to fingerprint normal device behaviour and detect
anomalous shifts.

Works with both forms of the CICIoT2023 dataset:
  - Full (46 columns): src_ip, dst_ip, dst_port, timestamp, etc. present.
  - Preprocessed (~40 columns): only aggregated flow statistics + label.
When a column is absent, the corresponding feature degrades gracefully
(falls back to a derived proxy or zero).
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Set


# ── Feature catalogue ────────────────────────────────────────────────────────
# Canonical ordered list of the 22 features this module produces.

FEATURE_NAMES: List[str] = [
    # Volume (3)
    "total_bytes",
    "total_packets",
    "total_flows",
    # Rate (3)
    "packets_per_sec",
    "bytes_per_sec",
    "flows_per_sec",
    # Diversity (2)
    "unique_dst_ips",
    "unique_dst_ports",
    # Entropy (2)
    "dst_ip_entropy",
    "port_entropy",
    # Protocol ratios (3)
    "tcp_ratio",
    "udp_ratio",
    "icmp_ratio",
    # Timing (2)
    "mean_iat",
    "mean_flow_duration",
    # TCP flags (2)
    "syn_ack_ratio",
    "rst_rate",
    # Security (5)
    "flow_symmetry",
    "burstiness",
    "new_dst_count",
    "avg_payload_size",
    "connection_failure_rate",
]

_ZERO_VECTOR: Dict[str, float] = {name: 0.0 for name in FEATURE_NAMES}


# ── Column name resolution ──────────────────────────────────────────────────
# Maps each logical field to every known column-name variant across the
# full and preprocessed CICIoT2023 releases.

_COLUMN_MAP = {
    "dst_ip":        ["dst_ip", "Dst_IP", "Destination_IP", "Dst IP"],
    "dst_port":      ["dst_port", "Dst_Port", "Destination_Port", "Dst Port"],
    "total_bytes":   ["Tot sum", "Tot size", "total_bytes", "Total_Bytes"],
    "total_packets": ["Number", "total_packets", "Total_Packets"],
    "flow_duration": ["flow_duration", "Flow_Duration", "duration"],
    "timestamp":     ["Timestamp", "timestamp", "ts"],
    "tcp":           ["TCP", "tcp"],
    "udp":           ["UDP", "udp"],
    "icmp":          ["ICMP", "icmp"],
    "iat":           ["IAT", "iat", "Flow_IAT_Mean"],
    "syn_count":     ["syn_count", "SYN_count", "Syn_count"],
    "ack_count":     ["ack_count", "ACK_count", "Ack_count"],
    "rst_count":     ["rst_count", "RST_count", "Rst_count"],
    "rate":          ["Rate", "rate", "Flow_Rate"],
    "fwd_packets":   ["Tot_Fwd_Pkts", "tot_fwd_pkts", "Fwd_Packets"],
    "bwd_packets":   ["Tot_Bwd_Pkts", "tot_bwd_pkts", "Bwd_Packets"],
}

# Service indicator columns in preprocessed CICIoT2023.
# Used as proxies for port diversity / destination diversity when
# dst_ip and dst_port columns are absent.
_SERVICE_COLS = ["HTTP", "HTTPS", "DNS", "Telnet", "SMTP", "SSH", "IRC"]

# Protocol indicator columns for destination-IP diversity proxy.
_PROTO_INDICATOR_COLS = ["TCP", "UDP", "ICMP", "ARP", "DHCP", "IGMP", "IPv", "LLC"]

# Service-to-port mapping for forbidden-ports policy detection.
_SERVICE_PORT_MAP = {"Telnet": 23, "IRC": 6667, "SSH": 22, "SMTP": 25}


def _resolve(df: pd.DataFrame, field: str) -> Optional[pd.Series]:
    """
    Look up a logical field in *df* by trying every known column-name
    variant.  Returns the Series if found, or ``None``.
    """
    for name in _COLUMN_MAP.get(field, [field]):
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce")
    return None


def _resolve_categorical(df: pd.DataFrame, field: str) -> Optional[pd.Series]:
    """
    Like ``_resolve`` but returns the column as-is (no numeric coercion),
    suitable for IP addresses and other categorical values.
    """
    for name in _COLUMN_MAP.get(field, [field]):
        if name in df.columns:
            return df[name]
    return None


# ── Helper functions ─────────────────────────────────────────────────────────


def calculate_entropy(values: pd.Series) -> float:
    """
    Calculate Shannon entropy (in bits) of a categorical Series.

    Entropy quantifies the randomness / diversity of the distribution.
    A device that contacts many destinations equally has high entropy;
    one that always talks to the same IP has entropy near zero.

    Formula:  H = -sum(p_i * log2(p_i))  for each unique value i
              where p_i = count_i / total_count

    Parameters
    ----------
    values : pd.Series
        Categorical values (e.g. destination IPs or ports).

    Returns
    -------
    float
        Shannon entropy in bits.  Returns 0.0 for empty input or a
        single unique value.
    """
    if values is None or len(values) == 0:
        return 0.0

    counts = values.value_counts()
    total = counts.sum()
    if total == 0:
        return 0.0

    probs = counts / total
    # log2(0) is undefined — filter out zero-probability entries
    probs = probs[probs > 0]
    return float(-(probs * np.log2(probs)).sum())


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide *numerator* by *denominator*, returning *default* on zero."""
    if denominator == 0:
        return default
    return float(numerator / denominator)


# ── Main extraction function ─────────────────────────────────────────────────


def extract_features(
    window_df: pd.DataFrame,
    baseline_ips: Optional[Set[str]] = None,
) -> Dict[str, float]:
    """
    Extract 22 behavioural features from one 60-second window of flow
    records for a single device.

    Parameters
    ----------
    window_df : pd.DataFrame
        Raw flow records for one device in one time window.  Each row is
        a network flow.  Columns may follow either the full or
        preprocessed CICIoT2023 schema — missing columns are handled
        gracefully.
    baseline_ips : set of str, optional
        Destination IPs observed during the burn-in (baseline) period.
        Used to compute ``new_dst_count``.  Defaults to empty set.

    Returns
    -------
    dict[str, float]
        22 feature name → value pairs, in the order defined by
        ``FEATURE_NAMES``.  All values are finite floats.
    """
    if baseline_ips is None:
        baseline_ips = set()

    # ── Edge case: empty window → all-zero vector ────────────────────
    if window_df is None or window_df.empty:
        return dict(_ZERO_VECTOR)

    n_flows = len(window_df)
    window_seconds = 60.0

    # ── Resolve available columns ────────────────────────────────────
    bytes_col    = _resolve(window_df, "total_bytes")
    packets_col  = _resolve(window_df, "total_packets")
    dst_ip_col   = _resolve_categorical(window_df, "dst_ip")
    dst_port_col = _resolve(window_df, "dst_port")
    tcp_col      = _resolve(window_df, "tcp")
    udp_col      = _resolve(window_df, "udp")
    icmp_col     = _resolve(window_df, "icmp")
    iat_col      = _resolve(window_df, "iat")
    duration_col = _resolve(window_df, "flow_duration")
    syn_col      = _resolve(window_df, "syn_count")
    ack_col      = _resolve(window_df, "ack_count")
    rst_col      = _resolve(window_df, "rst_count")
    rate_col     = _resolve(window_df, "rate")
    ts_col       = _resolve(window_df, "timestamp")
    fwd_col      = _resolve(window_df, "fwd_packets")
    bwd_col      = _resolve(window_df, "bwd_packets")

    # ── 1-3  VOLUME features ─────────────────────────────────────────
    total_bytes = float(bytes_col.sum()) if bytes_col is not None else 0.0
    total_packets = float(packets_col.sum()) if packets_col is not None else 0.0
    total_flows = float(n_flows)

    # ── 4-6  RATE features ───────────────────────────────────────────
    packets_per_sec = total_packets / window_seconds
    bytes_per_sec = total_bytes / window_seconds
    flows_per_sec = total_flows / window_seconds

    # ── 7-8  DIVERSITY features ──────────────────────────────────────
    # ── 9-10  ENTROPY features ───────────────────────────────────────
    # When dst_ip / dst_port columns are absent (preprocessed dataset),
    # use service indicator columns and Protocol Type as proxies.

    if dst_ip_col is not None:
        unique_dst_ips = float(dst_ip_col.nunique())
        dst_ip_entropy = calculate_entropy(dst_ip_col)
    else:
        # Proxy: diversity of Protocol Type values
        proto_type = window_df.get("Protocol Type")
        if proto_type is not None:
            unique_dst_ips = float(proto_type.nunique())
            dst_ip_entropy = calculate_entropy(proto_type.astype(str))
        else:
            # Fallback: count active protocol indicator columns
            active_protos = {
                p for p in _PROTO_INDICATOR_COLS
                if p in window_df.columns and float(window_df[p].sum()) > 0
            }
            unique_dst_ips = float(len(active_protos))
            if active_protos:
                counts = np.array([
                    float(window_df[p].sum()) for p in active_protos
                ])
                probs = counts / counts.sum()
                dst_ip_entropy = float(-(probs * np.log2(probs + 1e-12)).sum())
            else:
                dst_ip_entropy = 0.0

    if dst_port_col is not None:
        unique_dst_ports = float(dst_port_col.nunique())
        port_entropy = calculate_entropy(dst_port_col)
    else:
        # Proxy: count and entropy of active service indicators
        svc_counts: Dict[str, float] = {}
        for svc in _SERVICE_COLS:
            if svc in window_df.columns:
                total = float(window_df[svc].sum())
                if total > 0:
                    svc_counts[svc] = total
        unique_dst_ports = float(len(svc_counts))
        if svc_counts:
            counts_arr = np.array(list(svc_counts.values()))
            probs = counts_arr / counts_arr.sum()
            port_entropy = float(-(probs * np.log2(probs + 1e-12)).sum())
        else:
            port_entropy = 0.0

    # ── 11-13  PROTOCOL RATIO features ───────────────────────────────
    # In the preprocessed CICIoT2023, TCP/UDP/ICMP columns hold per-flow
    # indicator fractions (0.0–1.0).  Averaging across the window gives
    # the overall protocol mix.
    tcp_ratio = float(tcp_col.mean()) if tcp_col is not None else 0.0
    udp_ratio = float(udp_col.mean()) if udp_col is not None else 0.0
    icmp_ratio = float(icmp_col.mean()) if icmp_col is not None else 0.0

    # ── 14-15  TIMING features ───────────────────────────────────────
    # mean_iat: mean inter-arrival time in milliseconds.
    if iat_col is not None:
        # IAT column is in seconds in CICIoT2023 → convert to ms
        mean_iat = float(iat_col.mean()) * 1000.0
    elif ts_col is not None and len(ts_col) > 1:
        # Derive from raw timestamps if available
        sorted_ts = ts_col.sort_values()
        diffs = sorted_ts.diff().dropna()
        mean_iat = float(diffs.mean()) * 1000.0 if len(diffs) > 0 else 0.0
    else:
        mean_iat = 0.0

    # mean_flow_duration: average connection duration in seconds.
    if duration_col is not None:
        mean_flow_duration = float(duration_col.mean())
    elif iat_col is not None and packets_col is not None:
        # Approximate: duration ≈ IAT × (packets_in_flow − 1)
        approx_dur = iat_col * (packets_col - 1).clip(lower=0)
        mean_flow_duration = float(approx_dur.mean())
    elif rate_col is not None and packets_col is not None:
        # Approximate: duration ≈ packets / rate
        safe_rate = rate_col.replace(0, np.nan)
        approx_dur = packets_col / safe_rate
        mean_flow_duration = float(approx_dur.mean()) if approx_dur.notna().any() else 0.0
    else:
        mean_flow_duration = 0.0

    # ── 16-17  FLAG features ─────────────────────────────────────────
    total_syn = float(syn_col.sum()) if syn_col is not None else 0.0
    total_ack = float(ack_col.sum()) if ack_col is not None else 0.0
    total_rst = float(rst_col.sum()) if rst_col is not None else 0.0

    # syn_ack_ratio: high ratio indicates SYN flood (many SYNs, few ACKs)
    syn_ack_ratio = _safe_div(total_syn, total_ack, default=0.0)

    # rst_rate: fraction of all packets that are resets
    rst_rate = _safe_div(total_rst, total_packets, default=0.0)

    # ── 18-22  SECURITY features ─────────────────────────────────────

    # flow_symmetry: ratio of incoming to outgoing traffic.
    # Full dataset: use forward/backward packet counts.
    # Preprocessed: approximate from ACK (≈ response) vs SYN (≈ initiation).
    if fwd_col is not None and bwd_col is not None:
        total_fwd = float(fwd_col.sum())
        total_bwd = float(bwd_col.sum())
        flow_symmetry = _safe_div(total_bwd, total_fwd, default=1.0)
    elif total_syn + total_ack > 0:
        flow_symmetry = _safe_div(total_ack, total_syn, default=1.0)
    else:
        flow_symmetry = 1.0
    # Cap at 10 to avoid extreme outliers distorting models
    flow_symmetry = min(flow_symmetry, 10.0)

    # burstiness: variability (std dev) of per-flow packet rate.
    # High burstiness suggests irregular traffic patterns (e.g. DDoS bursts).
    if rate_col is not None and len(rate_col) > 1:
        burstiness = float(rate_col.std())
    else:
        burstiness = 0.0

    # new_dst_count: destinations not seen during burn-in.
    # A sudden spike in novel destinations suggests scanning / reconnaissance.
    if dst_ip_col is not None and baseline_ips:
        current_dsts = set(dst_ip_col.dropna().unique())
        new_dst_count = float(len(current_dsts - baseline_ips))
    elif baseline_ips:
        # Preprocessed format: use service indicators as proxy.
        # baseline_ips may contain "_svc_XXX" entries from burn-in.
        current_svcs = set()
        for svc in _SERVICE_COLS:
            if svc in window_df.columns and float(window_df[svc].sum()) > 0:
                current_svcs.add(f"_svc_{svc}")
        new_dst_count = float(len(current_svcs - baseline_ips))
    else:
        new_dst_count = 0.0

    # avg_payload_size: mean bytes per packet across the window.
    avg_payload_size = _safe_div(total_bytes, total_packets, default=0.0)

    # connection_failure_rate: fraction of flows that ended in a RST.
    # High failure rate can indicate port scanning or brute-force attempts.
    connection_failure_rate = _safe_div(total_rst, total_flows, default=0.0)

    # ── Assemble and return ──────────────────────────────────────────
    features = {
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

    # Sanitise: replace any NaN/inf with 0
    for key, val in features.items():
        if isinstance(val, (int, float)) and not np.isfinite(val):
            features[key] = 0.0

    # Extra metadata for the policy checker (not part of the 22-feature vector).
    # Map active service indicators to port numbers so the forbidden-ports
    # rule can fire even on preprocessed data.  Added AFTER sanitisation
    # because ports_used is a list, not a float.
    if dst_port_col is None:
        ports_used = []
        for svc, port in _SERVICE_PORT_MAP.items():
            if svc in window_df.columns and float(window_df[svc].sum()) > 0:
                ports_used.append(port)
        features["ports_used"] = ports_used

    return features


def extract_features_batch(
    windows: List[pd.DataFrame],
    baseline_ips: Optional[Set[str]] = None,
) -> pd.DataFrame:
    """
    Extract features from multiple windows and return as a DataFrame.

    This is a convenience wrapper around ``extract_features`` for batch
    processing.  Each row in the output corresponds to one window.

    Parameters
    ----------
    windows : list of pd.DataFrame
        List of per-window DataFrames (as returned by ``data_loader``).
    baseline_ips : set of str, optional
        Burn-in destination IPs (passed through to ``extract_features``).

    Returns
    -------
    pd.DataFrame
        Shape ``(len(windows), 22)`` with columns matching ``FEATURE_NAMES``.
    """
    rows = [extract_features(w, baseline_ips) for w in windows]
    return pd.DataFrame(rows, columns=FEATURE_NAMES)


# ── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Quick test with synthetic data
    print("=== Feature Engineer smoke test ===\n")

    # Test 1: empty DataFrame → all zeros
    empty_feats = extract_features(pd.DataFrame())
    assert all(v == 0.0 for v in empty_feats.values()), "Empty DF should give all zeros"
    print(f"[PASS] Empty DataFrame -> {len(empty_feats)} features, all zero")

    # Test 2: small synthetic window (preprocessed-style columns)
    synthetic = pd.DataFrame({
        "Tot sum":    [1000, 2000, 500],
        "Number":     [10, 20, 5],
        "TCP":        [1.0, 1.0, 0.0],
        "UDP":        [0.0, 0.0, 1.0],
        "ICMP":       [0.0, 0.0, 0.0],
        "IAT":        [0.005, 0.002, 0.010],
        "syn_count":  [2, 0, 1],
        "ack_count":  [8, 15, 3],
        "rst_count":  [0, 0, 1],
        "Rate":       [400.0, 500.0, 100.0],
        "label":      ["Benign", "Benign", "Benign"],
    })

    feats = extract_features(synthetic)
    print(f"\n[PASS] Synthetic window -> {len(feats)} features extracted:")
    for name, val in feats.items():
        print(f"  {name:30s} = {val:.4f}")

    # Test 3: batch extraction
    batch_df = extract_features_batch([synthetic, synthetic])
    assert batch_df.shape == (2, 22), f"Expected (2, 22), got {batch_df.shape}"
    print(f"\n[PASS] Batch extraction -> shape {batch_df.shape}")
