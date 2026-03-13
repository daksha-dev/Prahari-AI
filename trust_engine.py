"""
trust_engine.py - IoT Trust & Drift Analytics System

Computes and maintains a per-device trust score on a 0-100 scale.

Design principles
-----------------
**Quadratic penalty** -- The penalty is proportional to the *square* of
the effective anomaly score, not linear.  This creates a natural noise
floor: small fluctuations (score ~0.1) produce negligible penalties
(0.15 points) and are effectively ignored, while strong anomalies
(score ~0.8) incur severe hits (9.6+ points).  This avoids the need for
an additional hard cutoff and gives the system a smooth sensitivity
curve.

**Asymmetric trust (slow recovery)** -- Trust is fast to lose and slow
to rebuild, mirroring real-world trust dynamics.  At the default
recovery rate of 0.3 per clean window (60 seconds), a device that
drops to zero takes ~333 windows (~5.5 hours) of clean behaviour to
fully recover.  A two-minute pause in an attack barely registers.

**Drift amplification** -- Drift does not penalise directly.  Instead
it *multiplies* the anomaly score before penalty computation:
``effective = anomaly * drift_factor``.  If the anomaly score is zero,
drift has no effect.  If the anomaly is high and drift is confirmed,
the penalty roughly doubles.  This captures the insight that anomalies
during distribution drift are more dangerous than isolated spikes.

**No recovery during drift** -- When drift is confirmed the recovery
term is zeroed out.  This prevents the score from slowly climbing back
while the device's behaviour is still shifting, forcing the system (or
operator) to wait until the drift resolves.

**Direct policy penalties** -- Rule-based policy violations (forbidden
ports, SYN floods, etc.) are subtracted directly without squaring or
thresholding.  Hard rules encode domain certainty and should always
have immediate effect.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ── Metadata record ──────────────────────────────────────────────────────────


@dataclass
class TrustMetadata:
    """
    Detailed breakdown of a single trust-score update.  Stored for every
    window so the explainability engine can attribute score changes.
    """

    window_index: int
    trust_score: float
    severity: str
    anomaly_score: float
    effective_anomaly: float
    drift_factor: float
    drift_confirmed: bool
    anomaly_penalty: float
    policy_penalty: float
    recovery: float


# ── Severity helpers ─────────────────────────────────────────────────────────

_SEVERITY_ORDER = ["CRITICAL", "HIGH", "WARNING", "NORMAL"]

_SEVERITY_COLORS = {
    "NORMAL": "green",
    "WARNING": "yellow",
    "HIGH": "orange",
    "CRITICAL": "red",
}


# ── Pure helper functions ────────────────────────────────────────────────────


def compute_penalty(
    anomaly_score: float,
    drift_factor: float,
    penalty_multiplier: float,
) -> float:
    """
    Quadratic penalty from the effective anomaly score.

    ``penalty = multiplier * (anomaly * drift_factor) ** 2``

    Examples (multiplier=15, drift_factor=1.0):
        anomaly=0.1  ->  0.15
        anomaly=0.5  ->  3.75
        anomaly=0.8  ->  9.60
    """
    effective = anomaly_score * drift_factor
    return penalty_multiplier * (effective ** 2)


def compute_recovery(
    anomaly_score: float,
    drift_confirmed: bool,
    recovery_rate: float,
) -> float:
    """
    Recovery points for the current window.

    Returns ``recovery_rate * (1 - anomaly_score)`` when the device is
    not drifting, or ``0.0`` when drift is confirmed (no recovery
    allowed during active distribution shift).
    """
    if drift_confirmed:
        return 0.0
    return recovery_rate * (1.0 - anomaly_score)


def should_apply_penalty(anomaly_score: float, threshold: float) -> bool:
    """True when the anomaly score meets or exceeds the noise threshold."""
    return anomaly_score >= threshold


# ── Trust engine ─────────────────────────────────────────────────────────────


class TrustEngine:
    """
    Maintains and updates a single device's trust score.

    One ``TrustEngine`` instance is created per device.  The main loop
    calls ``update()`` once per window with the outputs of the anomaly
    detector, drift detector, and policy checker.

    Typical score trajectories
    --------------------------
    * **Clean device** -- score stays at 100.  Tiny anomaly noise
      (< threshold) is filtered and recovery tops it back up.
    * **Sudden attack** -- score drops fast due to quadratic penalty.
      A single window with anomaly=0.8 costs ~9.6 points.
    * **Slow drift** -- gradual decline.  Recovery partially offsets
      small penalties, creating a plateau until drift confirmation
      disables recovery and the score falls faster.
    * **Post-attack** -- score recovers at ~0.3 points per clean
      window.  Takes hours to return to full trust.
    """

    def __init__(self, config: dict) -> None:
        trust_cfg = config.get("trust", {})
        anomaly_cfg = config.get("anomaly", {})
        severity_cfg = config.get("severity", {})

        self._initial_score: float = float(trust_cfg.get("initial_score", 100))
        self._penalty_multiplier: float = float(trust_cfg.get("penalty_multiplier", 15))
        self._recovery_rate: float = float(trust_cfg.get("recovery_rate", 0.3))
        self._min_score: float = float(trust_cfg.get("min_score", 0))
        self._max_score: float = float(trust_cfg.get("max_score", 100))
        self._anomaly_threshold: float = float(anomaly_cfg.get("anomaly_threshold", 0.15))

        # Severity bands: list of (low, high, label) sorted by low bound
        self._severity_bands: List[Tuple[float, float, str]] = []
        for label, bounds in severity_cfg.items():
            if isinstance(bounds, list) and len(bounds) == 2:
                self._severity_bands.append((float(bounds[0]), float(bounds[1]), label.upper()))
        self._severity_bands.sort(key=lambda b: b[0])

        # Default bands if config is missing / empty
        if not self._severity_bands:
            self._severity_bands = [
                (0, 30, "CRITICAL"),
                (30, 50, "HIGH"),
                (50, 70, "WARNING"),
                (70, 100, "NORMAL"),
            ]

        self._score: float = self._initial_score
        self._history: List[float] = [self._initial_score]
        self._metadata_history: List[TrustMetadata] = []
        self._window_counter: int = 0

    # ── core update ──────────────────────────────────────────────────

    def update(
        self,
        anomaly_score: float,
        drift_factor: float,
        drift_confirmed: bool,
        policy_penalty: float,
    ) -> float:
        """
        Apply one window's worth of evidence to the trust score.

        Parameters
        ----------
        anomaly_score : float
            Smoothed blended anomaly score in [0, 1].
        drift_factor : float
            Penalty amplifier from the drift detector (1.0-2.0).
        drift_confirmed : bool
            True when 2+ drift signals agree.
        policy_penalty : float
            Direct penalty from policy rule violations (>= 0).

        Returns
        -------
        float
            Updated trust score clamped to [min_score, max_score].
        """
        self._window_counter += 1

        # 1. Threshold filter: suppress sub-threshold noise
        if not should_apply_penalty(anomaly_score, self._anomaly_threshold):
            effective_anomaly_score = 0.0
        else:
            effective_anomaly_score = anomaly_score

        # 2. Effective anomaly (drift-amplified)
        effective_anomaly = effective_anomaly_score * drift_factor

        # 3. Quadratic anomaly penalty
        anomaly_penalty = compute_penalty(
            effective_anomaly_score, drift_factor, self._penalty_multiplier
        )

        # 4. Recovery (zero during confirmed drift)
        recovery = compute_recovery(
            effective_anomaly_score, drift_confirmed, self._recovery_rate
        )

        # 5. Update score
        new_score = self._score - anomaly_penalty - policy_penalty + recovery

        # 6. Clamp
        new_score = max(self._min_score, min(self._max_score, new_score))

        self._score = new_score
        self._history.append(new_score)

        # Record metadata for explainability
        self._metadata_history.append(
            TrustMetadata(
                window_index=self._window_counter,
                trust_score=new_score,
                severity=self.get_severity_level(),
                anomaly_score=anomaly_score,
                effective_anomaly=effective_anomaly,
                drift_factor=drift_factor,
                drift_confirmed=drift_confirmed,
                anomaly_penalty=anomaly_penalty,
                policy_penalty=policy_penalty,
                recovery=recovery,
            )
        )

        return new_score

    # ── queries ──────────────────────────────────────────────────────

    def get_score(self) -> float:
        """Return the current trust score."""
        return self._score

    def get_severity_level(self) -> str:
        """
        Map the current score to a severity label using the configured
        bands.

        Returns one of ``"NORMAL"``, ``"WARNING"``, ``"HIGH"``, or
        ``"CRITICAL"``.
        """
        for low, high, label in self._severity_bands:
            if low <= self._score < high:
                return label
        # Score exactly at max_score falls in the highest band
        if self._score >= self._severity_bands[-1][1]:
            return self._severity_bands[-1][2]
        return "CRITICAL"

    def get_severity_color(self) -> str:
        """Return the color string for the current severity level."""
        return _SEVERITY_COLORS.get(self.get_severity_level(), "red")

    def get_score_history(self) -> List[float]:
        """Return the full list of trust scores (one per window + initial)."""
        return list(self._history)

    def get_metadata_history(self) -> List[TrustMetadata]:
        """Return detailed metadata for every ``update()`` call."""
        return list(self._metadata_history)

    def get_score_trajectory(self) -> List[Tuple[int, float]]:
        """
        Return ``(window_index, score)`` pairs for trend analysis.
        Index 0 is the initial score before any updates.
        """
        return list(enumerate(self._history))

    def estimate_time_to_critical(self) -> Optional[int]:
        """
        If the score is declining, estimate how many windows until it
        drops below the critical threshold (30).

        Uses the average per-window change over the last 10 windows.
        Returns ``None`` if the score is stable or rising.
        """
        if len(self._history) < 3:
            return None

        recent = self._history[-min(10, len(self._history)):]
        deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        avg_delta = sum(deltas) / len(deltas)

        if avg_delta >= 0:
            return None  # not declining

        # Find the critical threshold (lowest severity band upper bound)
        critical_bound = 30.0
        for low, high, label in self._severity_bands:
            if label == "CRITICAL":
                critical_bound = high
                break

        if self._score <= critical_bound:
            return 0  # already critical

        windows_remaining = (self._score - critical_bound) / abs(avg_delta)
        return max(1, int(windows_remaining))

    # ── reset ────────────────────────────────────────────────────────

    def reset_score(self) -> None:
        """Reset to initial score and clear all history."""
        self._score = self._initial_score
        self._history = [self._initial_score]
        self._metadata_history = []
        self._window_counter = 0
