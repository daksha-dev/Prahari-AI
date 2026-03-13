"""
explainability.py — IoT Trust & Drift Analytics System

Generates human-readable evidence reports that explain **why** a device was
flagged and **what** changed.

How it works
------------
1. **Z-score analysis** — For each of the 22 behavioural features, the
   current value is compared to the device's burn-in baseline (first 30
   windows).  A z-score measures how many standard deviations the current
   value is from the baseline mean:

       z = (current_value − baseline_mean) / baseline_std

   * |z| < 2   → normal (within 2 std devs — ~95 % of values)
   * 2 ≤ |z| < 3 → unusual (2-3 std devs — only ~5 % of values)
   * |z| ≥ 3    → highly unusual (> 3 std devs — only ~0.3 % of values)

2. **Top-N deviating features** — The top 5 features (configurable) with
   the highest absolute z-score are included in the report.  These tell a
   human analyst *exactly* what about the device's behaviour is different,
   without forcing them to compare all 22 numbers manually.

3. **Severity mapping** — The trust score is mapped to a recommended
   action / severity level so that operational teams know what to do:

       70–100 → NORMAL   → Monitor
       50–70  → WARNING  → Investigate
       30–50  → HIGH     → Isolate
        0–30  → CRITICAL → Block

4. **Device type inference** — Based purely on baseline traffic patterns,
   the engine *guesses* what kind of IoT device it is.  This is heuristic
   and not definitive; it helps analysts prioritise (e.g. a compromised
   camera is more concerning than a thermostat).

Example reports
---------------
**Slow drift scenario** — A video camera slowly escalates traffic over
weeks.  Trust drifts from 100 → 60.  Report shows moderate feature
deviations (z ≈ 2–3), ADWIN + chi-squared signals, and recommends
investigation.

**Sudden attack scenario** — A thermostat joins a SYN flood botnet.
Trust drops from 100 → 15 in two windows.  Report shows extreme z-scores
(z > 10), SYN flood + bandwidth policy violations, and recommends
immediate blocking.

**Clean device scenario** — All features within baseline range.  Report
confirms normal operation with trust score 95 and no deviations.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np


# ── Human-readable feature labels ────────────────────────────────────────────
# Maps internal feature keys (from feature_engineer.py) to analyst-friendly
# names used in reports.

_HUMAN_FEATURE_NAMES: Dict[str, str] = {
    "total_bytes":              "Total Bytes Sent/Received",
    "total_packets":            "Total Packets",
    "total_flows":              "Total Network Flows",
    "packets_per_sec":          "Packets per Second",
    "bytes_per_sec":            "Bytes per Second",
    "flows_per_sec":            "Flows per Second",
    "unique_dst_ips":           "Unique Destination IPs",
    "unique_dst_ports":         "Unique Destination Ports",
    "dst_ip_entropy":           "Destination IP Entropy",
    "port_entropy":             "Port Usage Entropy",
    "tcp_ratio":                "TCP Protocol Ratio",
    "udp_ratio":                "UDP Protocol Ratio",
    "icmp_ratio":               "ICMP Protocol Ratio",
    "mean_iat":                 "Mean Inter-Arrival Time (ms)",
    "mean_flow_duration":       "Mean Flow Duration (sec)",
    "syn_ack_ratio":            "SYN/ACK Ratio",
    "rst_rate":                 "Connection Reset Rate",
    "flow_symmetry":            "Flow Symmetry (In/Out Ratio)",
    "burstiness":               "Traffic Burstiness",
    "new_dst_count":            "New Destination IPs (Not in Baseline)",
    "avg_payload_size":         "Average Payload Size (bytes)",
    "connection_failure_rate":  "Connection Failure Rate",
}


# ── Canonical feature order (must match feature_engineer.FEATURE_NAMES) ──────

FEATURE_NAMES: List[str] = [
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


# ── Policy violation descriptions (keyed by rule_name) ───────────────────────

_POLICY_DESCRIPTIONS: Dict[str, str] = {
    "excessive_destinations": "Device contacted more unique IPs than allowed",
    "bandwidth_spike":        "Average throughput exceeded safe threshold",
    "forbidden_ports":        "Traffic on known-dangerous port detected",
    "protocol_violation":     "Protocol not seen during baseline appeared",
    "syn_flood":              "SYN/ACK ratio indicates SYN flood attack",
}


# ═════════════════════════════════════════════════════════════════════════════
#  ExplainabilityEngine
# ═════════════════════════════════════════════════════════════════════════════


class ExplainabilityEngine:
    """
    Generates comprehensive, human-readable evidence reports for every
    device whose trust score drops below threshold.

    The engine does **not** perform anomaly detection, drift detection,
    policy checking, or trust scoring — those are handled by their
    respective modules.  Instead, it takes their *outputs* and weaves
    them into a coherent narrative that analysts can act upon.

    Parameters
    ----------
    config : dict
        Full parsed ``config.yaml``.  Explainability settings are read
        from ``config['explainability']``.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._feature_names = list(FEATURE_NAMES)

        explain_cfg = config.get("explainability", {})
        self._min_zscore = float(explain_cfg.get("min_zscore_to_report", 2.0))
        self._top_n = int(explain_cfg.get("top_n_features", 5))
        self._score_threshold = float(
            explain_cfg.get("generate_on_score_below", 70)
        )

        # Severity ranges from config (or defaults)
        sev_cfg = config.get("severity", {})
        self._severity_ranges = {
            "NORMAL":   sev_cfg.get("normal",   [70, 100]),
            "WARNING":  sev_cfg.get("warning",  [50, 70]),
            "HIGH":     sev_cfg.get("high",     [30, 50]),
            "CRITICAL": sev_cfg.get("critical", [0, 30]),
        }

        # Policy config for enriching violation details
        self._policy_cfg = config.get("policy", {})

    # ─────────────────────────────────────────────────────────────────────
    #  Z-score computation
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def compute_zscore(value: float, baseline_array: np.ndarray) -> float:
        """
        Compute the z-score of *value* relative to *baseline_array*.

        The z-score tells us how many standard deviations *value* is
        from the baseline mean.  A z-score of 3.0 means the value is
        3× the typical variation away from normal — very unusual.

        Parameters
        ----------
        value : float
            Current feature value.
        baseline_array : numpy.ndarray, shape (30,)
            Values of this feature across the 30 burn-in windows.

        Returns
        -------
        float
            Z-score.  Returns 0.0 if the baseline has no variation
            (std < 1e-10), since every window had the same value and
            the current one matches.
        """
        mean = float(np.mean(baseline_array))
        std = float(np.std(baseline_array))
        if std < 1e-10:
            return 0.0
        return (value - mean) / std

    # ─────────────────────────────────────────────────────────────────────
    #  Top-deviating features
    # ─────────────────────────────────────────────────────────────────────

    def get_top_deviating_features(
        self,
        features: dict,
        burn_in_features: np.ndarray,
        top_n: int = 5,
    ) -> List[Tuple[str, float, float, float, float]]:
        """
        Identify the features whose current values deviate most from
        baseline.

        Parameters
        ----------
        features : dict
            Current window's 22-feature dict.
        burn_in_features : numpy.ndarray, shape (30, 22)
            Feature matrix from the 30 burn-in windows (rows = windows,
            columns = features in ``FEATURE_NAMES`` order).
        top_n : int
            Maximum number of deviating features to return.

        Returns
        -------
        list of (feature_name, current_value, baseline_mean,
                 baseline_std, z_score)
            Sorted by |z_score| descending, filtered to features with
            |z_score| >= ``min_zscore_to_report``.
        """
        deviations: List[Tuple[str, float, float, float, float]] = []

        for idx, fname in enumerate(self._feature_names):
            current = float(features.get(fname, 0.0))
            baseline_col = burn_in_features[:, idx]
            mean = float(np.mean(baseline_col))
            std = float(np.std(baseline_col))
            z = self.compute_zscore(current, baseline_col)

            if abs(z) >= self._min_zscore:
                deviations.append((fname, current, mean, std, z))

        # Sort by absolute z-score descending
        deviations.sort(key=lambda t: abs(t[4]), reverse=True)
        return deviations[:top_n]

    # ─────────────────────────────────────────────────────────────────────
    #  Severity / action helpers
    # ─────────────────────────────────────────────────────────────────────

    def _get_severity_label(self, trust_score: float) -> Tuple[str, str]:
        """Return (severity_label, severity_color) for the trust score."""
        if trust_score >= 70:
            return "NORMAL", "green"
        elif trust_score >= 50:
            return "WARNING", "yellow"
        elif trust_score >= 30:
            return "HIGH", "orange"
        else:
            return "CRITICAL", "red"

    @staticmethod
    def get_severity_action(trust_score: float) -> str:
        """
        Map trust score to a recommended operational action.

        * 70–100 → **Monitor** — continue normal monitoring.
        * 50–70  → **Investigate** — increase log collection, check for
          recent firmware updates or config changes.
        * 30–50  → **Isolate** — move to isolated VLAN, restrict network
          access while investigation proceeds.
        * 0–30   → **Block** — disconnect from network immediately, the
          device is almost certainly compromised.
        """
        if trust_score >= 70:
            return "Monitor"
        elif trust_score >= 50:
            return "Investigate"
        elif trust_score >= 30:
            return "Isolate"
        else:
            return "Block"

    @staticmethod
    def interpret_anomaly_score(
        anomaly_score: float,
    ) -> Tuple[str, str]:
        """
        Classify the anomaly severity and provide a human explanation.

        * 0.00–0.15 → **Clean** — below detection threshold, noise.
        * 0.15–0.40 → **Mild anomaly** — small behavioural deviation.
        * 0.40–0.70 → **Moderate anomaly** — noticeable deviation.
        * 0.70–1.00 → **Severe anomaly** — major departure from baseline.
        """
        if anomaly_score < 0.15:
            return (
                "Clean",
                "Anomaly score is below the detection threshold. "
                "Current behaviour is consistent with the device's baseline.",
            )
        elif anomaly_score < 0.4:
            return (
                "Mild anomaly",
                f"Anomaly score of {anomaly_score:.2f} indicates a small "
                "behavioural deviation. This may be a transient fluctuation "
                "or the early stage of a pattern shift.",
            )
        elif anomaly_score < 0.7:
            return (
                "Moderate anomaly",
                f"Anomaly score of {anomaly_score:.2f} indicates a "
                "noticeable deviation from the baseline. The device's "
                "traffic pattern has changed significantly.",
            )
        else:
            return (
                "Severe anomaly",
                f"Anomaly score of {anomaly_score:.2f} indicates a major "
                "departure from the established baseline. The device is "
                "behaving very differently from its normal pattern.",
            )

    @staticmethod
    def interpret_feature_deviation(
        z_score: float,
    ) -> Tuple[str, str]:
        """
        Classify a single feature's deviation severity.

        * |z| < 2  → **Minor** — within normal variation.
        * 2 ≤ |z| < 3 → **Moderate** — unusual but not extreme.
        * |z| ≥ 3  → **Severe** — highly abnormal.
        """
        abs_z = abs(z_score)
        if abs_z < 2.0:
            return "Minor", "Within normal variation"
        elif abs_z < 3.0:
            return "Moderate", "Unusual but not extreme"
        else:
            return "Severe", "Highly abnormal"

    # ─────────────────────────────────────────────────────────────────────
    #  Behavioural context helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def infer_device_type(burn_in_features: np.ndarray) -> str:
        """
        Guess the device type from baseline traffic patterns.

        This is a **heuristic** — it is not definitive.  The guess is
        based on typical traffic signatures of common IoT device
        categories during their normal (burn-in) operation.

        Heuristics used
        ---------------
        * High bytes/sec + high burstiness → camera / media streamer
          (constant video streams with variable bitrate).
        * Low bytes/sec + low packet rate → sensor / thermostat
          (periodic telemetry, small payloads).
        * High unique destination IPs + high port entropy → scanner
          or server (talks to many endpoints on varied ports).
        * Balanced pattern → general IoT device.
        """
        # Column indices (matching FEATURE_NAMES order)
        IDX_BYTES_PER_SEC = 4
        IDX_PACKETS_PER_SEC = 3
        IDX_UNIQUE_DST_IPS = 6
        IDX_PORT_ENTROPY = 9
        IDX_BURSTINESS = 18

        mean_bps = float(np.mean(burn_in_features[:, IDX_BYTES_PER_SEC]))
        mean_pps = float(np.mean(burn_in_features[:, IDX_PACKETS_PER_SEC]))
        mean_dst = float(np.mean(burn_in_features[:, IDX_UNIQUE_DST_IPS]))
        mean_ent = float(np.mean(burn_in_features[:, IDX_PORT_ENTROPY]))
        mean_burst = float(np.mean(burn_in_features[:, IDX_BURSTINESS]))

        if mean_bps > 5000 and mean_burst > 50:
            return "Video camera or media streamer"
        elif mean_bps < 500 and mean_pps < 10:
            return "Sensor or thermostat"
        elif mean_dst > 10 and mean_ent > 2.0:
            return "Network scanning tool or server"
        else:
            return "General IoT device"

    @staticmethod
    def describe_normal_pattern(burn_in_features: np.ndarray) -> str:
        """
        Summarise the device's normal (baseline) behaviour in plain
        language, extracted from burn-in feature means.
        """
        means = np.mean(burn_in_features, axis=0)

        bps = means[4]      # bytes_per_sec
        pps = means[3]      # packets_per_sec
        dst = means[6]      # unique_dst_ips
        tcp = means[10]     # tcp_ratio
        udp = means[11]     # udp_ratio

        # Build protocol description
        protocols = []
        if tcp > 0.1:
            protocols.append(f"TCP ({tcp * 100:.0f}%)")
        if udp > 0.1:
            protocols.append(f"UDP ({udp * 100:.0f}%)")
        proto_str = " and ".join(protocols) if protocols else "mixed protocols"

        return (
            f"Sends ~{bps:,.0f} bytes/sec, ~{pps:,.0f} packets/sec to "
            f"{dst:.0f}–{dst + 2:.0f} destinations using {proto_str}"
        )

    @staticmethod
    def describe_current_pattern(features: dict) -> str:
        """
        Summarise the device's current behaviour in the same plain-
        language format as the baseline summary.
        """
        bps = float(features.get("bytes_per_sec", 0))
        pps = float(features.get("packets_per_sec", 0))
        dst = float(features.get("unique_dst_ips", 0))
        tcp = float(features.get("tcp_ratio", 0))
        udp = float(features.get("udp_ratio", 0))

        protocols = []
        if tcp > 0.1:
            protocols.append(f"TCP ({tcp * 100:.0f}%)")
        if udp > 0.1:
            protocols.append(f"UDP ({udp * 100:.0f}%)")
        proto_str = " and ".join(protocols) if protocols else "mixed protocols"

        return (
            f"Now sending ~{bps:,.0f} bytes/sec, ~{pps:,.0f} packets/sec "
            f"to {dst:.0f} destinations using {proto_str}"
        )

    # ─────────────────────────────────────────────────────────────────────
    #  Drift explanation
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_drift_explanation(drift_metadata: dict) -> str:
        """
        Explain what drift means for this device by combining all active
        signal descriptions into a coherent narrative.

        Drift signals
        -------------
        * **ADWIN** — detects a shift in the average anomaly score.
          "The anomaly rate has increased on average."
        * **Chi-squared** — detects distributional change in features.
          "The device's behaviour has shifted compared to its baseline."
        * **Model disagreement** — Isolation Forest and Half-Space Trees
          disagree persistently.
          "Adaptive model has been slowly influenced by gradual attack."
        """
        parts: List[str] = []

        if drift_metadata.get("adwin_signal", False):
            parts.append(
                "ADWIN detected a shift in the anomaly rate — the device's "
                "average anomaly score has increased over recent windows"
            )
        if drift_metadata.get("chi_squared_signal", False):
            parts.append(
                "Chi-squared testing shows the device's feature distribution "
                "has shifted significantly compared to its initial baseline"
            )
        if drift_metadata.get("disagreement_signal", False):
            parts.append(
                "The offline and online anomaly models persistently disagree, "
                "suggesting the adaptive model has been slowly influenced by "
                "a gradual behaviour change (possible slow poisoning attack)"
            )

        if not parts:
            return "No drift signals are active. Device behaviour is stable."

        narrative = ". ".join(parts) + "."
        if drift_metadata.get("confirmed", False):
            narrative += (
                " Multiple signals converge, confirming a genuine "
                "distribution drift — this is unlikely to be noise."
            )
        return narrative

    # ─────────────────────────────────────────────────────────────────────
    #  Actionable insights
    # ─────────────────────────────────────────────────────────────────────

    def generate_actionable_insights(
        self,
        features: dict,
        burn_in_features: Optional[np.ndarray],
        drift_metadata: Optional[dict],
        policy_violations: List[str],
        trust_score: float,
    ) -> List[str]:
        """
        Generate 3–5 specific, actionable recommendations prioritised
        by severity.  Each insight is a single sentence that tells an
        operator *what to do*, not just what happened.
        """
        insights: List[str] = []

        # ── Feature-driven insights ──────────────────────────────────
        new_dst = float(features.get("new_dst_count", 0))
        if new_dst > 20:
            insights.append(
                f"Device is contacting {new_dst:.0f} new destination IPs "
                "not seen during baseline. Check for reconnaissance or "
                "worm propagation behaviour."
            )

        syn_ack = float(features.get("syn_ack_ratio", 0))
        if syn_ack > 5:
            insights.append(
                f"SYN/ACK ratio is {syn_ack:.1f}× (normal is ~1.0). "
                "This is a strong indicator of a SYN flood attack. "
                "Consider rate-limiting or blocking this device immediately."
            )

        bps = float(features.get("bytes_per_sec", 0))
        if bps > 100_000:
            baseline_bps = 0.0
            if burn_in_features is not None:
                baseline_bps = float(np.mean(burn_in_features[:, 4]))
            if baseline_bps > 0:
                ratio = bps / baseline_bps
                insights.append(
                    f"Throughput is {bps:,.0f} bytes/sec "
                    f"({ratio:.1f}× baseline average of "
                    f"{baseline_bps:,.0f} bytes/sec). "
                    "Investigate for volumetric DDoS participation or "
                    "data exfiltration."
                )
            else:
                insights.append(
                    f"Throughput is {bps:,.0f} bytes/sec, well above "
                    "the safe threshold. Investigate for DDoS or "
                    "exfiltration."
                )

        rst_rate = float(features.get("connection_failure_rate", 0))
        if rst_rate > 0.5:
            insights.append(
                f"Connection failure rate is {rst_rate * 100:.0f}%. "
                "Many connections are being reset, which may indicate "
                "port scanning or brute-force login attempts."
            )

        # ── Policy-driven insights ───────────────────────────────────
        for v in policy_violations:
            v_lower = v.lower()
            if "forbidden port" in v_lower or "4444" in v or "5555" in v:
                insights.append(
                    f"Policy violation: {v}. "
                    "These ports are associated with malware. "
                    "Investigate all connections on these ports."
                )
            elif "bandwidth" in v_lower:
                insights.append(
                    f"Policy violation: {v}. "
                    "Verify whether a firmware update or legitimate burst "
                    "explains the spike."
                )

        # ── Drift-driven insights ────────────────────────────────────
        dm = drift_metadata or {}
        if dm.get("confirmed", False):
            insights.append(
                "Confirmed distribution drift detected. The device's "
                "behaviour has fundamentally changed. Check if a firmware "
                "update or network reconfiguration occurred (legitimate "
                "change) or if this is a slow compromise."
            )
        if dm.get("disagreement_signal", False):
            insights.append(
                "The adaptive anomaly model disagrees with the offline "
                "model, suggesting the online model may have been slowly "
                "poisoned by gradual drift. Manual review is needed — do "
                "not rely only on the adaptive model's score."
            )

        # ── Trust-score-driven insights ──────────────────────────────
        if trust_score < 30:
            insights.append(
                f"Trust score is critically low ({trust_score:.0f}/100). "
                "Immediate isolation or blocking is recommended to protect "
                "the rest of the network."
            )
        elif trust_score < 50:
            insights.append(
                f"Trust score is low ({trust_score:.0f}/100). "
                "Move the device to an isolated VLAN and increase log "
                "collection before deciding on further action."
            )

        # Deduplicate while preserving order, then cap at 5
        seen: set = set()
        unique: List[str] = []
        for item in insights:
            key = item[:60]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:5]

    # ─────────────────────────────────────────────────────────────────────
    #  Detailed narrative
    # ─────────────────────────────────────────────────────────────────────

    def generate_detailed_narrative(self, evidence: dict) -> str:
        """
        Create a 2–3 paragraph narrative explanation combining all
        sections of the evidence report.  Written for non-technical
        security operators.
        """
        device = evidence.get("device_id") or "Unknown device"
        window = evidence.get("window_index")
        summary = evidence.get("summary", {})
        score = summary.get("trust_score", 0)
        severity = summary.get("severity", "UNKNOWN")
        action = summary.get("action_recommended", "Monitor")

        # ── Paragraph 1: summary ─────────────────────────────────────
        window_str = f" at window {window}" if window is not None else ""
        para1 = (
            f"Device {device}{window_str} received a trust score of "
            f"{score:.0f}/100 ({severity}). "
            f"Recommended action: {action}."
        )

        # ── Paragraph 2: what happened ───────────────────────────────
        anomaly = evidence.get("anomaly_analysis", {})
        drift = evidence.get("drift_analysis", {})
        feat_dev = evidence.get("feature_deviation_analysis", {})
        policy = evidence.get("policy_violations", {})

        parts: List[str] = []

        anomaly_status = anomaly.get("status", "Clean")
        if anomaly_status != "Clean":
            parts.append(
                f"The anomaly detector classified this window as "
                f"\"{anomaly_status}\" (score: "
                f"{anomaly.get('anomaly_score', 0):.2f})"
            )

        if drift.get("drift_detected", False):
            signals = drift.get("signals", {})
            active = signals.get("signals_active_count", 0)
            parts.append(
                f"Drift detection raised {active} signal(s)"
                + (" (confirmed)" if drift.get("drift_confirmed") else "")
            )

        n_deviated = feat_dev.get("num_features_above_threshold", 0)
        if n_deviated > 0:
            top = feat_dev.get("top_deviating_features", [])
            if top:
                names = [f.get("feature_name", "") for f in top[:3]]
                parts.append(
                    f"{n_deviated} features deviated significantly from "
                    f"baseline, especially: {', '.join(names)}"
                )

        n_violations = policy.get("total_violations", 0)
        if n_violations > 0:
            violations = policy.get("violations", [])
            v_names = [v.get("rule_name", "") for v in violations[:3]]
            parts.append(
                f"{n_violations} policy rule(s) were violated: "
                + ", ".join(v_names)
            )

        if parts:
            para2 = ". ".join(parts) + "."
        else:
            para2 = (
                "No anomalies, drift, or policy violations were detected "
                "in this window. The device is operating normally."
            )

        # ── Paragraph 3: interpretation and recommendation ───────────
        context = evidence.get("behavioral_context", {})
        device_type = context.get("device_type_inference", "Unknown device")

        if score < 30:
            para3 = (
                f"This {device_type} is almost certainly compromised or "
                "malfunctioning. Disconnect it from the network immediately "
                "and conduct a forensic examination of the device and any "
                "systems it communicated with during this period."
            )
        elif score < 50:
            para3 = (
                f"This {device_type} is showing strong indicators of "
                "compromise or significant misconfiguration. Isolate it on "
                "a restricted VLAN, increase logging, and investigate the "
                "source of the behavioural changes before allowing it back "
                "on the main network."
            )
        elif score < 70:
            para3 = (
                f"This {device_type} has mild behavioural anomalies that "
                "warrant investigation. Check whether recent firmware "
                "updates, network changes, or legitimate usage shifts "
                "explain the deviation. Continue monitoring closely."
            )
        else:
            para3 = (
                f"This {device_type} is operating within expected "
                "parameters. No action is required at this time. Continue "
                "routine monitoring."
            )

        return f"{para1}\n\n{para2}\n\n{para3}"

    # ─────────────────────────────────────────────────────────────────────
    #  Feature deviation formatting
    # ─────────────────────────────────────────────────────────────────────

    def _format_deviation_interpretation(
        self,
        fname: str,
        current: float,
        baseline_mean: float,
        z_score: float,
    ) -> str:
        """
        Build a human-readable description of how a feature changed,
        using comparisons and percentages instead of raw numbers.
        """
        human_name = _HUMAN_FEATURE_NAMES.get(fname, fname)

        if baseline_mean != 0:
            ratio = current / baseline_mean
            pct_change = (ratio - 1.0) * 100
            direction = "increased" if z_score > 0 else "decreased"

            if abs(ratio) >= 2.0:
                return (
                    f"{human_name} {direction} to {current:,.2f} "
                    f"({ratio:.1f}× the baseline average of "
                    f"{baseline_mean:,.2f})"
                )
            else:
                return (
                    f"{human_name} {direction} by {abs(pct_change):.0f}% "
                    f"(from baseline {baseline_mean:,.2f} to {current:,.2f})"
                )
        else:
            if current > 0:
                return (
                    f"{human_name} appeared at {current:,.2f} — baseline "
                    "was consistently zero"
                )
            return f"{human_name} is at {current:,.2f} (baseline was zero)"

    # ─────────────────────────────────────────────────────────────────────
    #  Policy violation enrichment
    # ─────────────────────────────────────────────────────────────────────

    def _enrich_policy_violations(
        self,
        policy_violations: List[str],
    ) -> List[dict]:
        """
        Convert raw violation description strings into structured dicts
        with rule_name, description, threshold, and penalty fields.
        """
        enriched: List[dict] = []

        # Map keywords in violation descriptions → rule names
        rule_keywords = {
            "excessive":   "excessive_destinations",
            "bandwidth":   "bandwidth_spike",
            "forbidden":   "forbidden_ports",
            "protocol":    "protocol_violation",
            "syn flood":   "syn_flood",
            "syn/ack":     "syn_flood",
        }

        for v_desc in policy_violations:
            matched_rule = None
            for kw, rule in rule_keywords.items():
                if kw.lower() in v_desc.lower():
                    matched_rule = rule
                    break

            if matched_rule:
                rule_cfg = self._policy_cfg.get(matched_rule, {})
                penalty = int(rule_cfg.get("penalty", 0))
                # Extract threshold from config
                if matched_rule == "excessive_destinations":
                    threshold = rule_cfg.get("threshold", 20)
                elif matched_rule == "bandwidth_spike":
                    threshold = rule_cfg.get("threshold_bytes_sec", 100_000)
                elif matched_rule == "syn_flood":
                    threshold = rule_cfg.get("syn_ack_ratio", 5.0)
                elif matched_rule == "forbidden_ports":
                    threshold = str(rule_cfg.get("ports", [23, 4444, 5555, 6667]))
                else:
                    threshold = "N/A"

                enriched.append({
                    "rule_name": matched_rule,
                    "description": v_desc,
                    "actual_value": v_desc,  # raw text; caller may enrich
                    "threshold": threshold,
                    "penalty": penalty,
                })
            else:
                enriched.append({
                    "rule_name": "unknown",
                    "description": v_desc,
                    "actual_value": "N/A",
                    "threshold": "N/A",
                    "penalty": 0,
                })
        return enriched

    # ─────────────────────────────────────────────────────────────────────
    #  Main report generator
    # ─────────────────────────────────────────────────────────────────────

    def generate_evidence_report(
        self,
        features: dict,
        burn_in_features: Optional[np.ndarray],
        trust_score: float,
        anomaly_score: float,
        drift_metadata: Optional[dict],
        policy_violations: List[str],
        device_id: Optional[str] = None,
        window_index: Optional[int] = None,
    ) -> dict:
        """
        Build a comprehensive evidence report explaining why a device
        was flagged and what changed.

        Parameters
        ----------
        features : dict
            Current window's 22-feature dict (from feature_engineer).
        burn_in_features : numpy.ndarray or None
            Shape ``(30, 22)`` baseline matrix.  If ``None``, feature
            deviation analysis is skipped.
        trust_score : float
            Current trust score, 0–100.
        anomaly_score : float
            Current blended anomaly score, 0–1.
        drift_metadata : dict or None
            Drift signals and factors from drift_detector.
        policy_violations : list of str
            Human-readable violation descriptions from policy_checker.
        device_id : str, optional
            e.g. ``"192.168.1.5"``.
        window_index : int, optional
            e.g. ``47``.

        Returns
        -------
        dict
            Structured evidence report (see module docstring for schema).

        Example
        -------
        >>> engine = ExplainabilityEngine(config)
        >>> evidence = engine.generate_evidence_report(
        ...     features=current_features,
        ...     burn_in_features=burn_in_array,
        ...     trust_score=42,
        ...     anomaly_score=0.75,
        ...     drift_metadata={
        ...         'adwin_signal': True,
        ...         'chi_squared_signal': True,
        ...         'disagreement_signal': False,
        ...         'confirmed': True,
        ...         'drift_factor': 1.8,
        ...         'signals_active': 2,
        ...     },
        ...     policy_violations=['Bandwidth spike', 'Forbidden port: 4444'],
        ...     device_id='192.168.1.5',
        ...     window_index=47,
        ... )
        """
        # Normalise optional inputs
        dm = drift_metadata or {}
        pv = policy_violations or []
        ts = round(float(trust_score), 2)
        a_score = round(float(anomaly_score), 2)

        # ── 1. Summary ───────────────────────────────────────────────
        severity_label, severity_color = self._get_severity_label(ts)
        action = self.get_severity_action(ts)

        summary = {
            "trust_score": ts,
            "severity": severity_label,
            "severity_color": severity_color,
            "action_recommended": action,
        }

        # ── 2. Anomaly analysis ──────────────────────────────────────
        anom_status, anom_explanation = self.interpret_anomaly_score(a_score)
        anomaly_threshold = float(
            self._config.get("anomaly", {}).get("anomaly_threshold", 0.15)
        )
        anomaly_analysis = {
            "anomaly_score": a_score,
            "anomaly_interpretation": anom_explanation,
            "threshold": round(anomaly_threshold, 2),
            "status": anom_status,
        }

        # ── 3. Drift analysis ────────────────────────────────────────
        adwin_active = bool(dm.get("adwin_signal", False))
        chi2_active = bool(dm.get("chi_squared_signal", False))
        disagree_active = bool(dm.get("disagreement_signal", False))
        signals_count = sum([adwin_active, chi2_active, disagree_active])
        drift_confirmed = bool(dm.get("confirmed", False))
        drift_detected = signals_count > 0
        drift_factor = round(float(dm.get("drift_factor", 1.0)), 2)

        drift_interpretation = self.generate_drift_explanation(dm)

        drift_analysis = {
            "drift_detected": drift_detected,
            "drift_confirmed": drift_confirmed,
            "signals": {
                "adwin": adwin_active,
                "chi_squared": chi2_active,
                "model_disagreement": disagree_active,
                "signals_active_count": signals_count,
            },
            "drift_factor": drift_factor,
            "drift_interpretation": drift_interpretation,
        }

        # ── 4. Feature deviation analysis ────────────────────────────
        if burn_in_features is not None:
            top_deviations = self.get_top_deviating_features(
                features, burn_in_features, top_n=self._top_n
            )

            # Count ALL features above threshold (not just top-N)
            all_above = 0
            for idx, fname in enumerate(self._feature_names):
                val = float(features.get(fname, 0.0))
                z = self.compute_zscore(val, burn_in_features[:, idx])
                if abs(z) >= self._min_zscore:
                    all_above += 1

            formatted_deviations: List[dict] = []
            for fname, current, mean, std, z in top_deviations:
                sev, sev_expl = self.interpret_feature_deviation(z)
                interp = self._format_deviation_interpretation(
                    fname, current, mean, z
                )
                formatted_deviations.append({
                    "feature_name": _HUMAN_FEATURE_NAMES.get(fname, fname),
                    "current_value": round(current, 2),
                    "baseline_mean": round(mean, 2),
                    "baseline_std": round(std, 2),
                    "z_score": round(z, 2),
                    "deviation_interpretation": interp,
                    "severity": sev,
                })

            feature_deviation_analysis = {
                "top_deviating_features": formatted_deviations,
                "num_features_above_threshold": all_above,
                "total_features_analyzed": len(self._feature_names),
            }
        else:
            feature_deviation_analysis = {
                "top_deviating_features": [],
                "num_features_above_threshold": 0,
                "total_features_analyzed": len(self._feature_names),
            }

        # ── 5. Policy violations ─────────────────────────────────────
        enriched_violations = self._enrich_policy_violations(pv)
        total_penalty = sum(v.get("penalty", 0) for v in enriched_violations)

        policy_section = {
            "violations_detected": len(pv) > 0,
            "total_violations": len(pv),
            "violations": enriched_violations,
            "total_policy_penalty": total_penalty,
        }

        # ── 6. Behavioural context ───────────────────────────────────
        if burn_in_features is not None:
            device_type = self.infer_device_type(burn_in_features)
            normal_pattern = self.describe_normal_pattern(burn_in_features)
        else:
            device_type = "Unknown device (no baseline available)"
            normal_pattern = "Baseline data not available"

        current_pattern = self.describe_current_pattern(features)

        # Describe what changed
        if burn_in_features is not None:
            baseline_bps = float(np.mean(burn_in_features[:, 4]))
            current_bps = float(features.get("bytes_per_sec", 0))
            baseline_dst = float(np.mean(burn_in_features[:, 6]))
            current_dst = float(features.get("unique_dst_ips", 0))

            changes: List[str] = []
            if baseline_bps > 0 and current_bps > baseline_bps * 2:
                ratio = current_bps / baseline_bps
                changes.append(
                    f"Traffic volume increased by {ratio:.1f}×"
                )
            if current_dst > baseline_dst * 2:
                changes.append(
                    f"Contacting {current_dst:.0f} destinations "
                    f"(was ~{baseline_dst:.0f})"
                )
            if dm.get("confirmed", False):
                changes.append("Gradual behaviour shift confirmed by drift detectors")

            pattern_change = "; ".join(changes) if changes else "No major pattern change detected"
        else:
            pattern_change = "Cannot compare — no baseline available"

        behavioral_context = {
            "device_type_inference": device_type,
            "normal_pattern_summary": normal_pattern,
            "current_pattern_summary": current_pattern,
            "pattern_change": pattern_change,
        }

        # ── 7. Actionable insights ───────────────────────────────────
        actionable_insights = self.generate_actionable_insights(
            features, burn_in_features, dm, pv, ts
        )

        # ── Assemble evidence ────────────────────────────────────────
        evidence: dict = {
            "device_id": device_id or None,
            "window_index": window_index,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "anomaly_analysis": anomaly_analysis,
            "drift_analysis": drift_analysis,
            "feature_deviation_analysis": feature_deviation_analysis,
            "policy_violations": policy_section,
            "behavioral_context": behavioral_context,
            "actionable_insights": actionable_insights,
            "detailed_explanation": "",  # placeholder — filled below
        }

        # ── 8. Detailed narrative ────────────────────────────────────
        evidence["detailed_explanation"] = self.generate_detailed_narrative(
            evidence
        )

        return evidence


# ═════════════════════════════════════════════════════════════════════════════
#  Smoke test
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    print("=" * 72)
    print("  ExplainabilityEngine — Smoke Tests")
    print("=" * 72)

    # Minimal config
    test_config = {
        "explainability": {
            "min_zscore_to_report": 2.0,
            "top_n_features": 5,
            "generate_on_score_below": 70,
        },
        "anomaly": {"anomaly_threshold": 0.15},
        "severity": {
            "normal": [70, 100],
            "warning": [50, 70],
            "high": [30, 50],
            "critical": [0, 30],
        },
        "policy": {
            "excessive_destinations": {"enabled": True, "threshold": 20, "penalty": 15},
            "bandwidth_spike": {"enabled": True, "threshold_bytes_sec": 100000, "penalty": 20},
            "forbidden_ports": {"enabled": True, "ports": [23, 4444, 5555, 6667], "penalty": 25},
            "protocol_violation": {"enabled": True, "penalty": 10},
            "syn_flood": {"enabled": True, "syn_ack_ratio": 5.0, "penalty": 15},
        },
    }

    engine = ExplainabilityEngine(test_config)

    # ── Test 1: z-score ──────────────────────────────────────────────
    baseline = np.array([10.0, 12.0, 11.0, 9.0, 10.5] * 6)  # 30 values
    z = engine.compute_zscore(20.0, baseline)
    print(f"\n[Test 1] Z-score of 20.0 vs baseline mean "
          f"{np.mean(baseline):.2f}: z = {z:.2f}")
    assert abs(z) > 2.0, "Expected z > 2 for a noticeable deviation"
    print("  PASS")

    # ── Test 2: z-score edge case (zero std) ─────────────────────────
    flat = np.ones(30) * 5.0
    z_flat = engine.compute_zscore(5.0, flat)
    print(f"\n[Test 2] Z-score with zero std: {z_flat}")
    assert z_flat == 0.0, "Expected 0.0 for zero-std baseline"
    print("  PASS")

    # ── Test 3: severity mapping ─────────────────────────────────────
    for score, expected in [(85, "Monitor"), (60, "Investigate"),
                            (40, "Isolate"), (15, "Block")]:
        got = engine.get_severity_action(score)
        assert got == expected, f"Score {score}: expected {expected}, got {got}"
    print(f"\n[Test 3] Severity mapping: PASS")

    # ── Test 4: anomaly interpretation ───────────────────────────────
    status, _ = engine.interpret_anomaly_score(0.05)
    assert status == "Clean"
    status, _ = engine.interpret_anomaly_score(0.3)
    assert status == "Mild anomaly"
    status, _ = engine.interpret_anomaly_score(0.55)
    assert status == "Moderate anomaly"
    status, _ = engine.interpret_anomaly_score(0.85)
    assert status == "Severe anomaly"
    print(f"[Test 4] Anomaly interpretation: PASS")

    # ── Test 5: full report (sudden attack scenario) ─────────────────
    np.random.seed(42)
    burn_in = np.random.randn(30, 22) * 2 + 10  # baseline ~ mean 10

    # Simulate attack: spike several features
    attack_features = {name: 10.0 for name in FEATURE_NAMES}
    attack_features["bytes_per_sec"] = 250_000     # massive spike
    attack_features["unique_dst_ips"] = 45          # scanning
    attack_features["syn_ack_ratio"] = 12.0         # SYN flood
    attack_features["new_dst_count"] = 40           # reconnaissance
    attack_features["connection_failure_rate"] = 0.8

    evidence = engine.generate_evidence_report(
        features=attack_features,
        burn_in_features=burn_in,
        trust_score=22,
        anomaly_score=0.85,
        drift_metadata={
            "adwin_signal": True,
            "chi_squared_signal": True,
            "disagreement_signal": False,
            "confirmed": True,
            "drift_factor": 1.8,
            "signals_active": 2,
        },
        policy_violations=[
            "Bandwidth spike (250,000 bytes/sec > threshold 100,000)",
            "Forbidden port (port 4444)",
        ],
        device_id="192.168.1.5",
        window_index=47,
    )

    print(f"\n[Test 5] Sudden attack report:")
    print(f"  Device: {evidence['device_id']}")
    print(f"  Trust: {evidence['summary']['trust_score']}")
    print(f"  Severity: {evidence['summary']['severity']}")
    print(f"  Action: {evidence['summary']['action_recommended']}")
    print(f"  Anomaly: {evidence['anomaly_analysis']['status']}")
    print(f"  Drift confirmed: {evidence['drift_analysis']['drift_confirmed']}")
    print(f"  Policy violations: {evidence['policy_violations']['total_violations']}")
    print(f"  Top deviating features: "
          f"{len(evidence['feature_deviation_analysis']['top_deviating_features'])}")
    print(f"  Insights: {len(evidence['actionable_insights'])}")
    print(f"\n  --- Detailed Explanation ---")
    print(f"  {evidence['detailed_explanation'][:500]}...")
    assert evidence["summary"]["severity"] == "CRITICAL"
    assert evidence["summary"]["action_recommended"] == "Block"
    print("  PASS")

    # ── Test 6: clean device ─────────────────────────────────────────
    clean_features = {name: 10.0 for name in FEATURE_NAMES}
    clean_evidence = engine.generate_evidence_report(
        features=clean_features,
        burn_in_features=burn_in,
        trust_score=95,
        anomaly_score=0.05,
        drift_metadata=None,
        policy_violations=[],
        device_id="192.168.1.20",
        window_index=100,
    )
    print(f"\n[Test 6] Clean device report:")
    print(f"  Severity: {clean_evidence['summary']['severity']}")
    print(f"  Action: {clean_evidence['summary']['action_recommended']}")
    print(f"  Anomaly: {clean_evidence['anomaly_analysis']['status']}")
    assert clean_evidence["summary"]["severity"] == "NORMAL"
    assert clean_evidence["policy_violations"]["violations_detected"] is False
    print("  PASS")

    # ── Test 7: None burn-in (edge case) ─────────────────────────────
    no_baseline = engine.generate_evidence_report(
        features=clean_features,
        burn_in_features=None,
        trust_score=50,
        anomaly_score=0.3,
        drift_metadata=None,
        policy_violations=[],
    )
    assert no_baseline["feature_deviation_analysis"]["top_deviating_features"] == []
    print(f"\n[Test 7] None burn-in edge case: PASS")

    print(f"\n{'=' * 72}")
    print("  All smoke tests passed ✓")
    print(f"{'=' * 72}")
