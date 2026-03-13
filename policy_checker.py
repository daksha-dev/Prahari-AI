"""
policy_checker.py - IoT Trust & Drift Analytics System

Rule-based policy engine that detects known attack signatures and
suspicious behaviour patterns from the 22-feature vector.

This complements the statistical anomaly detector: while Isolation Forest
and Half-Space Trees learn what "abnormal" looks like from data, the
policy checker encodes domain knowledge -- specific attack indicators
that the ML models might miss or under-weight.

Rules and penalty rationale
---------------------------
Each rule targets a distinct IoT attack class.  Penalties reflect the
severity and confidence of the indicator:

* **Forbidden ports (25)** -- highest penalty because seeing traffic on
  ports 23/4444/5555/6667 is a near-certain indicator of Telnet abuse,
  Metasploit shells, or IRC-based C&C.  Very low false-positive rate.

* **Bandwidth spike (20)** -- volumetric DDoS participation or data
  exfiltration.  High penalty but slightly below forbidden ports because
  legitimate firmware updates can cause brief spikes.

* **Excessive destinations (15)** & **SYN flood (15)** -- strong
  indicators of reconnaissance/worm propagation and SYN flood attacks
  respectively.  Moderate penalty because network topology changes can
  occasionally cause false positives.

* **Protocol violation (10)** -- lowest penalty because protocol mix can
  shift legitimately (e.g. a device enabling mDNS).  Still worth
  flagging as it may corroborate other signals.

All thresholds and penalties are read from ``config.yaml`` so they can
be tuned without code changes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ── Violation record ─────────────────────────────────────────────────────────


@dataclass
class PolicyViolation:
    """
    Structured record of a single policy violation, used by the
    explainability engine for evidence reports.
    """

    rule_name: str          # e.g. "excessive_destinations"
    threshold: float        # configured threshold that was exceeded
    actual_value: float     # observed value in this window
    penalty: int            # trust-score penalty applied
    description: str        # human-readable one-liner


# ── Policy checker ───────────────────────────────────────────────────────────


class PolicyChecker:
    """
    Evaluates a fixed set of rule-based checks against each window's
    feature vector.  Every rule is independent -- one violation does not
    prevent others from being checked, and penalties are summed.

    Parameters
    ----------
    config : dict
        Full parsed ``config.yaml``.  Policy rules live under
        ``config['policy']``.
    """

    def __init__(self, config: dict) -> None:
        self._policy_cfg: dict = config.get("policy", {})
        self._last_violations: List[PolicyViolation] = []

    # ── config helpers ───────────────────────────────────────────────

    def _rule_cfg(self, rule_name: str) -> dict:
        """Return the sub-dict for *rule_name*, or empty dict."""
        return self._policy_cfg.get(rule_name, {})

    def is_rule_enabled(self, rule_name: str) -> bool:
        """Check whether a rule is enabled in the config."""
        return self._rule_cfg(rule_name).get("enabled", False)

    def get_rule_penalty(self, rule_name: str) -> int:
        """Look up the configured penalty for *rule_name*."""
        return int(self._rule_cfg(rule_name).get("penalty", 0))

    @staticmethod
    def get_rule_description(rule_name: str, details: Optional[str] = None) -> str:
        """
        Build a human-readable description of a violation.

        Parameters
        ----------
        rule_name : str
            Internal rule identifier.
        details : str, optional
            Extra context (e.g. "35 > threshold 20").

        Returns
        -------
        str
            E.g. ``"Excessive new destinations (35 > threshold 20)"``
        """
        pretty = {
            "excessive_destinations": "Excessive new destinations",
            "bandwidth_spike": "Bandwidth spike",
            "forbidden_ports": "Forbidden port",
            "protocol_violation": "Protocol violation",
            "syn_flood": "SYN flood",
        }
        label = pretty.get(rule_name, rule_name)
        if details:
            return f"{label} ({details})"
        return label

    # ── safe feature access ──────────────────────────────────────────

    @staticmethod
    def _get(features: dict, key: str, default: float = 0.0) -> float:
        """
        Retrieve a feature value, returning *default* for missing or
        NaN values.
        """
        val = features.get(key, default)
        if val is None:
            return default
        try:
            val = float(val)
        except (TypeError, ValueError):
            return default
        # NaN check
        if val != val:
            return default
        return val

    # ── individual rule checks ───────────────────────────────────────

    def check_excessive_destinations(
        self,
        features: dict,
        baseline_ips: Optional[Set[str]],
        config: dict,
    ) -> Tuple[int, Optional[PolicyViolation]]:
        """
        Fires when a device contacts more new destination IPs than the
        threshold.  Typical of reconnaissance scanning or worm
        propagation.

        ``new_dst_count`` is computed by feature_engineer (count of
        destination IPs in this window not seen during burn-in).
        """
        rule = "excessive_destinations"
        if not self.is_rule_enabled(rule):
            return 0, None
        if baseline_ips is None or len(baseline_ips) == 0:
            return 0, None

        cfg = self._rule_cfg(rule)
        threshold = float(cfg.get("threshold", 20))
        penalty = self.get_rule_penalty(rule)
        actual = self._get(features, "new_dst_count")

        if actual > threshold:
            desc = self.get_rule_description(
                rule, f"{actual:.0f} > threshold {threshold:.0f}"
            )
            return penalty, PolicyViolation(rule, threshold, actual, penalty, desc)
        return 0, None

    def check_bandwidth_spike(
        self,
        features: dict,
        config: dict,
    ) -> Tuple[int, Optional[PolicyViolation]]:
        """
        Fires when average bytes/sec in the window exceeds the
        threshold.  Catches volumetric DDoS participation and data
        exfiltration.
        """
        rule = "bandwidth_spike"
        if not self.is_rule_enabled(rule):
            return 0, None

        cfg = self._rule_cfg(rule)
        threshold = float(cfg.get("threshold_bytes_sec", 100_000))
        penalty = self.get_rule_penalty(rule)
        actual = self._get(features, "bytes_per_sec")

        if actual > threshold:
            desc = self.get_rule_description(
                rule,
                f"{actual:,.0f} bytes/sec > threshold {threshold:,.0f}",
            )
            return penalty, PolicyViolation(rule, threshold, actual, penalty, desc)
        return 0, None

    def check_forbidden_ports(
        self,
        features: dict,
        config: dict,
        baseline_ports: Optional[Set[int]] = None,
    ) -> Tuple[int, Optional[PolicyViolation]]:
        """
        Fires when traffic is observed on known-dangerous ports that were
        NOT seen during the burn-in baseline.

        * Port 23  -- Telnet (primary Mirai propagation vector)
        * Port 4444 -- Metasploit default listener
        * Port 5555 -- Common backdoor / Android debug bridge
        * Port 6667 -- IRC (botnet command-and-control)

        The feature vector may carry a ``ports_used`` list (full
        dataset) with the actual destination ports observed in the
        window.  Ports already present during burn-in are excluded
        to avoid false positives from legitimate baseline traffic.
        """
        rule = "forbidden_ports"
        if not self.is_rule_enabled(rule):
            return 0, None

        cfg = self._rule_cfg(rule)
        forbidden = set(cfg.get("ports", [23, 4444, 5555, 6667]))
        penalty = self.get_rule_penalty(rule)

        ports_used = features.get("ports_used", [])
        if not ports_used:
            return 0, None

        # Convert to set of ints for reliable comparison
        try:
            ports_set = {int(p) for p in ports_used}
        except (TypeError, ValueError):
            return 0, None

        # Exclude ports that were already active during burn-in
        if baseline_ports:
            ports_set -= baseline_ports

        matched = ports_set & forbidden
        if matched:
            port_str = ", ".join(str(p) for p in sorted(matched))
            desc = self.get_rule_description(rule, f"port {port_str}")
            return penalty, PolicyViolation(
                rule, 0, float(min(matched)), penalty, desc
            )
        return 0, None

    def check_protocol_violation(
        self,
        features: dict,
        baseline_protocols: Optional[Set[str]],
        config: dict,
    ) -> Tuple[int, Optional[PolicyViolation]]:
        """
        Fires when the device uses a protocol not seen during its
        burn-in baseline.

        Protocol presence is inferred from the ratio features:
        ``tcp_ratio``, ``udp_ratio``, ``icmp_ratio``.  A ratio > 0
        means that protocol was active in this window.
        """
        rule = "protocol_violation"
        if not self.is_rule_enabled(rule):
            return 0, None
        if baseline_protocols is None or len(baseline_protocols) == 0:
            return 0, None

        penalty = self.get_rule_penalty(rule)

        protocol_map = {
            "tcp":  self._get(features, "tcp_ratio"),
            "udp":  self._get(features, "udp_ratio"),
            "icmp": self._get(features, "icmp_ratio"),
        }

        new_protocols = []
        for proto, ratio in protocol_map.items():
            if ratio > 0 and proto not in baseline_protocols:
                new_protocols.append(proto)

        if new_protocols:
            proto_str = ", ".join(new_protocols)
            desc = self.get_rule_description(
                rule, f"new protocol(s): {proto_str}"
            )
            return penalty, PolicyViolation(
                rule, 0, len(new_protocols), penalty, desc
            )
        return 0, None

    def check_syn_flood(
        self,
        features: dict,
        config: dict,
    ) -> Tuple[int, Optional[PolicyViolation]]:
        """
        Fires when the SYN-to-ACK ratio exceeds the threshold.

        A high ratio means many connection attempts without completion,
        which is the hallmark of a SYN flood attack.  Normal TCP
        traffic has a ratio near 1.0 (one SYN per ACK).
        """
        rule = "syn_flood"
        if not self.is_rule_enabled(rule):
            return 0, None

        cfg = self._rule_cfg(rule)
        threshold = float(cfg.get("syn_ack_ratio", 5.0))
        penalty = self.get_rule_penalty(rule)
        actual = self._get(features, "syn_ack_ratio")

        if actual > threshold:
            desc = self.get_rule_description(
                rule, f"SYN/ACK ratio {actual:.1f} > threshold {threshold:.1f}"
            )
            return penalty, PolicyViolation(rule, threshold, actual, penalty, desc)
        return 0, None

    # ── main entry point ─────────────────────────────────────────────

    def check_policies(
        self,
        features: Dict[str, float],
        baseline_ips: Optional[Set[str]],
        config: dict,
        baseline_protocols: Optional[Set[str]] = None,
        baseline_ports: Optional[Set[int]] = None,
    ) -> Tuple[int, List[str]]:
        """
        Run all enabled policy rules against the current window's
        features.

        Parameters
        ----------
        features : dict[str, float]
            22-feature vector (plus optional ``ports_used`` list).
        baseline_ips : set of str or None
            Destination IPs observed during burn-in.
        config : dict
            Full config (passed through for dynamic threshold access).
        baseline_protocols : set of str or None
            Protocols (``"tcp"``, ``"udp"``, ``"icmp"``) active during
            burn-in.

        Returns
        -------
        tuple of (total_penalty, violation_names)
            ``total_penalty`` is the sum of all triggered rule penalties.
            ``violation_names`` is a list of human-readable violation
            descriptions, in evaluation order.
        """
        self._last_violations = []
        total_penalty = 0
        violation_names: List[str] = []

        # Evaluation order: excessive_destinations -> bandwidth ->
        # forbidden_ports -> protocol -> syn_flood
        checks = [
            self.check_excessive_destinations(features, baseline_ips, config),
            self.check_bandwidth_spike(features, config),
            self.check_forbidden_ports(features, config, baseline_ports),
            self.check_protocol_violation(features, baseline_protocols, config),
            self.check_syn_flood(features, config),
        ]

        for penalty, violation in checks:
            if violation is not None:
                total_penalty += penalty
                violation_names.append(violation.description)
                self._last_violations.append(violation)

        return total_penalty, violation_names

    def get_violation_details(self) -> List[PolicyViolation]:
        """
        Return structured details of every violation from the last
        ``check_policies`` call.  Used by the explainability engine.
        """
        return list(self._last_violations)
