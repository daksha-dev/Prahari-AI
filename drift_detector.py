"""
drift_detector.py - IoT Trust & Drift Analytics System

Three-signal drift detection that identifies when a device's traffic
distribution has shifted away from its burn-in baseline.

Why three independent signals?
------------------------------
No single drift test is perfect.  ADWIN can false-fire on a noisy score
stream; chi-squared can flag natural diurnal variation; model disagreement
can occur transiently during legitimate usage spikes.  By requiring at
least 2-of-3 signals to fire simultaneously (configurable), we achieve a
much lower false-positive rate while still catching real distribution
shifts quickly.  Each signal probes a different axis of evidence:

1. **ADWIN** (Adaptive Windowing) -- a stream-based change-point detector
   from the River library.  It monitors the anomaly-score time series and
   triggers when it detects a statistically significant shift in the
   running mean.  Sensitive to both sudden jumps (e.g. a new attack) and
   gradual trends (e.g. slow model degradation).

2. **Chi-squared** -- a classical distribution comparison test.  For each
   of the 22 features, the detector bins the burn-in values into a
   histogram and compares against a histogram of the most recent N
   windows.  If enough features show statistically significant
   distributional change (p < threshold), the signal fires.  This catches
   multi-dimensional shifts that may not raise the anomaly score itself
   (e.g. if the device changes protocol mix without becoming more
   anomalous).

3. **Model disagreement** -- monitors whether the static Isolation Forest
   and the adaptive Half-Space Trees persistently disagree.  When IF
   flags traffic as anomalous but HST considers it normal for several
   consecutive windows, the HST may have been "poisoned" by a slow drift
   -- it adapted to the new (malicious) distribution while IF, being
   frozen, still correctly flags it.  This signal catches adaptive-model
   poisoning, a subtle failure mode that neither ADWIN nor chi-squared
   would reliably detect.

Drift factor
------------
When drift is confirmed the trust penalty for the current window is
amplified by a drift factor.  Each active signal contributes additively:

    factor = base + adwin_contrib + chi_sq_contrib + disagree_contrib

The factor is capped at ``max_factor`` (default 2.0) to prevent runaway
penalties.
"""

from typing import Dict, List, Tuple

import numpy as np
from river.drift import ADWIN
from scipy.stats import chi2_contingency


# ── Helper ───────────────────────────────────────────────────────────────────


def check_flatness(recent_features: np.ndarray) -> bool:
    """
    Check if the recent features are perfectly flat (frozen sensor).
    Returns True if the variance of all features across recent windows is exactly zero.
    """
    if recent_features.shape[0] < 2:
        return False
    std_dev = np.std(recent_features, axis=0)
    return bool(np.all(std_dev == 0))


def get_recent_features(
    feature_history: List[np.ndarray],
    window_index: int,
    num_windows: int,
) -> np.ndarray:
    """
    Extract the most recent *num_windows* feature vectors ending at
    *window_index* (inclusive) from *feature_history*.

    Parameters
    ----------
    feature_history : list of np.ndarray
        Each element is a 1-D array of shape ``(22,)``.
    window_index : int
        Current position in the history (0-based).
    num_windows : int
        How many recent windows to retrieve.

    Returns
    -------
    np.ndarray
        Shape ``(k, 22)`` where ``k = min(num_windows, available)``.
        If the history is empty, returns an empty ``(0, 22)`` array.
    """
    if not feature_history:
        return np.empty((0, 22))

    end = window_index + 1
    start = max(0, end - num_windows)
    subset = feature_history[start:end]

    if not subset:
        return np.empty((0, 22))

    return np.vstack(subset)


# ── Signal 1: ADWIN ─────────────────────────────────────────────────────────


class ADWINDetector:
    """
    Stream-based change-point detector for the anomaly score series.

    ADWIN (Adaptive Windowing) maintains a variable-length window of
    recent values and triggers when it can statistically prove that the
    distribution of the older portion differs from the newer portion.

    ``delta`` controls sensitivity: smaller values require stronger
    evidence before declaring a drift, reducing false positives at the
    cost of slower reaction.
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("drift", {}).get("adwin", {})
        self._enabled: bool = cfg.get("enabled", True)
        self._delta: float = cfg.get("delta", 0.002)
        self._clock: int = cfg.get("clock", 1)
        self._adwin = ADWIN(delta=self._delta, clock=self._clock)
        self._drift_detected: bool = False

    def update(self, anomaly_score: float) -> None:
        """Feed a new anomaly score and check for drift."""
        if not self._enabled:
            return
        self._adwin.update(anomaly_score)
        self._drift_detected = self._adwin.drift_detected

    def is_drifted(self) -> bool:
        """Return True if ADWIN detected a drift on the last update."""
        if not self._enabled:
            return False
        return self._drift_detected

    def reset(self) -> None:
        """Clear internal state and start fresh."""
        self._adwin = ADWIN(delta=self._delta, clock=self._clock)
        self._drift_detected = False


# ── Signal 2: Chi-squared ────────────────────────────────────────────────────


class ChiSquaredDriftDetector:
    """
    Compares the feature distribution of recent windows against the
    burn-in baseline using per-feature chi-squared contingency tests.

    Intuition: if the device's behaviour has shifted, the histogram
    shape of at least a few features will look significantly different
    from the baseline.  We count how many features exceed the
    significance threshold and fire when enough of them drift
    simultaneously.
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("drift", {}).get("chi_squared", {})
        self._enabled: bool = cfg.get("enabled", True)
        self._p_threshold: float = cfg.get("p_threshold", 0.01)
        self._min_features_drifted: int = cfg.get("min_features_drifted", 3)
        self._recent_windows: int = cfg.get("recent_windows", 10)
        self._last_drifted: bool = False
        self._last_drifted_count: int = 0

    def check_drift(
        self,
        burn_in_features: np.ndarray,
        recent_features: np.ndarray,
    ) -> bool:
        """
        Test whether the recent feature distribution differs significantly
        from the burn-in baseline.

        Parameters
        ----------
        burn_in_features : np.ndarray
            Shape ``(n_burn_in, 22)`` -- baseline feature matrix.
        recent_features : np.ndarray
            Shape ``(n_recent, 22)`` -- most recent windows.

        Returns
        -------
        bool
            True if the number of significantly drifted features meets
            the configured minimum.
        """
        if not self._enabled:
            self._last_drifted = False
            self._last_drifted_count = 0
            return False

        # Need at least 2 recent rows for a meaningful histogram
        if recent_features.shape[0] < 2:
            self._last_drifted = False
            self._last_drifted_count = 0
            return False

        n_features = burn_in_features.shape[1]
        drifted_count = 0

        for col in range(n_features):
            baseline_vals = burn_in_features[:, col]
            recent_vals = recent_features[:, col]

            # Build 10 histogram bins spanning both distributions.
            # Skip features whose combined range is zero (constant columns
            # such as new_dst_count=0 always) — they carry no signal.
            all_vals = np.concatenate([baseline_vals, recent_vals])
            try:
                bin_edges = np.histogram_bin_edges(all_vals, bins=10)
            except ValueError:
                continue

            baseline_hist, _ = np.histogram(baseline_vals, bins=bin_edges)
            recent_hist, _ = np.histogram(recent_vals, bins=bin_edges)

            # Add epsilon (+1) to avoid zero cells which would make
            # chi2_contingency degenerate
            baseline_hist = baseline_hist + 1
            recent_hist = recent_hist + 1

            contingency = np.array([baseline_hist, recent_hist])

            try:
                _, p_value, _, _ = chi2_contingency(contingency)
            except ValueError:
                # Degenerate table (e.g. all values identical) -- no drift
                continue

            if p_value < self._p_threshold:
                drifted_count += 1

        self._last_drifted_count = drifted_count
        self._last_drifted = drifted_count >= self._min_features_drifted
        return self._last_drifted

    def is_drifted(self) -> bool:
        """Return the result of the last ``check_drift`` call."""
        if not self._enabled:
            return False
        return self._last_drifted

    def get_drifted_feature_count(self) -> int:
        """How many features drifted in the last check (for diagnostics)."""
        return self._last_drifted_count


# ── Signal 3: Model disagreement ────────────────────────────────────────────


class ModelDisagreementDetector:
    """
    Detects persistent disagreement between the static Isolation Forest
    and the adaptive Half-Space Trees.

    When IF flags traffic as anomalous but HST considers it normal for
    several *consecutive* windows, the adaptive model may have been
    slowly poisoned -- it adapted to the new (malicious) distribution
    while IF, frozen at the baseline, still correctly flags it.

    The counter resets to zero as soon as a single window breaks the
    disagreement pattern, ensuring only sustained disagreement triggers
    the signal.
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("drift", {}).get("disagreement", {})
        self._enabled: bool = cfg.get("enabled", True)
        self._consecutive_required: int = cfg.get("consecutive_windows", 5)
        self._if_threshold: float = cfg.get("if_threshold", 0.5)
        self._hst_threshold: float = cfg.get("hst_threshold", 0.3)
        self._counter: int = 0

    def update(self, if_score: float, hst_score: float) -> None:
        """
        Feed the latest per-model scores and update the streak counter.

        Disagreement is defined as: IF considers the window anomalous
        (score > if_threshold) while HST considers it normal
        (score < hst_threshold).
        """
        if not self._enabled:
            return

        if if_score > self._if_threshold and hst_score < self._hst_threshold:
            self._counter += 1
        else:
            self._counter = 0

    def is_disagreement(self) -> bool:
        """True if the disagreement streak has reached the threshold."""
        if not self._enabled:
            return False
        return self._counter >= self._consecutive_required

    def get_counter(self) -> int:
        """Current streak length (for debugging / dashboards)."""
        return self._counter

    def reset(self) -> None:
        """Clear the streak counter."""
        self._counter = 0


# ── Orchestrator ─────────────────────────────────────────────────────────────


class DriftDetector:
    """
    Orchestrates the three independent drift signals and computes a
    confirmed drift decision plus a drift amplification factor.

    Typical per-window usage::

        drift_det.update_adwin(smoothed_anomaly_score)
        drift_det.update_chi_squared(burn_in_features, recent_features)
        drift_det.update_disagreement(if_score, hst_score)
        metadata = drift_det.compute_drift_metadata()
    """

    def __init__(self, config: dict) -> None:
        self._adwin = ADWINDetector(config)
        self._chi_sq = ChiSquaredDriftDetector(config)
        self._disagree = ModelDisagreementDetector(config)

        confirm_cfg = config.get("drift", {}).get("confirmation", {})
        self._signals_required: int = confirm_cfg.get("signals_required", 2)

        df_cfg = config.get("drift_factor", {})
        self._df_base: float = df_cfg.get("base", 1.0)
        self._df_adwin: float = df_cfg.get("adwin_contribution", 0.5)
        self._df_chi_sq: float = df_cfg.get("chi_squared_contribution", 0.3)
        self._df_disagree: float = df_cfg.get("disagreement_contribution", 0.2)
        self._df_max: float = df_cfg.get("max_factor", 2.0)

    # ── per-signal updates ───────────────────────────────────────────

    def update_adwin(self, anomaly_score: float) -> None:
        """Pass the smoothed anomaly score to the ADWIN detector."""
        self._adwin.update(anomaly_score)

    def update_chi_squared(
        self,
        burn_in_features: np.ndarray,
        recent_features: np.ndarray,
    ) -> None:
        """Run the chi-squared distribution test."""
        self._chi_sq.check_drift(burn_in_features, recent_features)

    def update_disagreement(self, if_score: float, hst_score: float) -> None:
        """Update the IF-vs-HST disagreement streak."""
        self._disagree.update(if_score, hst_score)

    # ── aggregated queries ───────────────────────────────────────────

    def get_drift_signals(self) -> Tuple[bool, bool, bool]:
        """
        Returns
        -------
        tuple of (adwin_drift, chi_drift, disagreement_drift)
        """
        return (
            self._adwin.is_drifted(),
            self._chi_sq.is_drifted(),
            self._disagree.is_disagreement(),
        )

    def is_drift_confirmed(self) -> bool:
        """
        True when the number of active drift signals meets or exceeds
        the configured threshold (default 2-of-3).

        Using a multi-signal confirmation rule dramatically reduces false
        positives: a single noisy detector cannot trigger a drift
        response on its own.
        """
        signals = self.get_drift_signals()
        return sum(signals) >= self._signals_required

    def get_drift_factor(
        self,
        adwin_drift: bool,
        chi_drift: bool,
        disagreement_drift: bool,
        flatness_drift: bool = False,
    ) -> float:
        """
        Compute the trust-penalty amplification factor from active signals.

        Each active signal adds its configured contribution to the base
        factor.  The result is capped at ``max_factor`` to prevent
        runaway penalties.

        Parameters
        ----------
        adwin_drift, chi_drift, disagreement_drift : bool
            Whether each signal is currently active.
        flatness_drift : bool
            Whether the signal exhibits flatness (frozen sensor).

        Returns
        -------
        float
            Drift factor in [base, max_factor] (typically [1.0, 2.0]).
        """
        factor = self._df_base
        if adwin_drift:
            factor += self._df_adwin
        if chi_drift:
            factor += self._df_chi_sq
        if disagreement_drift:
            factor += self._df_disagree
        if flatness_drift:
            factor += 0.5  # Extra penalty for flatness
        return min(factor, self._df_max)

    def compute_drift_metadata(self) -> Dict[str, object]:
        """
        Build a summary dict of current drift state for logging,
        dashboards, and the explainability module.

        Returns
        -------
        dict with keys:
            adwin_signal, chi_squared_signal, disagreement_signal : bool
            confirmed : bool
            drift_factor : float
            signals_active : int
        """
        adwin, chi_sq, disagree = self.get_drift_signals()
        signals_active = sum([adwin, chi_sq, disagree])

        return {
            "adwin_signal": adwin,
            "chi_squared_signal": chi_sq,
            "disagreement_signal": disagree,
            "confirmed": signals_active >= self._signals_required,
            "drift_factor": self.get_drift_factor(adwin, chi_sq, disagree),
            "signals_active": signals_active,
        }
