from __future__ import annotations

from collections import deque

import numpy as np
from river.drift import ADWIN
from scipy.stats import chi2_contingency


class DriftDetector:
    def __init__(self) -> None:
        self.adwin = ADWIN(delta=0.002)
        self.disagreement_streak = 0
        self.signal_history: deque[dict[str, bool | int | float]] = deque(maxlen=30)

    def update(
        self,
        burn_in: list[np.ndarray],
        feature_history: list[np.ndarray],
        combined_score: float,
        if_score: float,
        hst_score: float,
    ) -> dict[str, bool | int | float | list[str]]:
        self.adwin.update(float(combined_score))
        adwin_fired = bool(self.adwin.drift_detected)

        chi_count = self._chi_squared_count(burn_in, feature_history[-10:])
        chi_fired = chi_count >= 3

        if if_score > 0.5 and hst_score < 0.3:
            self.disagreement_streak += 1
        else:
            self.disagreement_streak = 0
        disagreement_fired = self.disagreement_streak >= 5

        fired = [
            name
            for name, active in {
                "adwin": adwin_fired,
                "chi_squared": chi_fired,
                "model_disagreement": disagreement_fired,
            }.items()
            if active
        ]
        confirmed = len(fired) >= 2
        factor = min(
            2.0,
            1.0
            + (0.5 if adwin_fired else 0.0)
            + (0.3 if chi_fired else 0.0)
            + (0.2 if disagreement_fired else 0.0),
        )
        result = {
            "adwin": adwin_fired,
            "chi_squared": chi_fired,
            "model_disagreement": disagreement_fired,
            "chi_squared_features": chi_count,
            "confirmed": confirmed,
            "factor": round(factor, 3),
            "fired": fired,
        }
        self.signal_history.append(result)
        return result

    @staticmethod
    def _chi_squared_count(burn_in: list[np.ndarray], recent: list[np.ndarray]) -> int:
        if len(burn_in) < 30 or len(recent) < 10:
            return 0
        base = np.vstack(burn_in)
        rec = np.vstack(recent)
        count = 0
        for column in range(base.shape[1]):
            values = np.concatenate([base[:, column], rec[:, column]])
            if float(values.max() - values.min()) < 1e-9:
                continue
            bins = np.histogram_bin_edges(values, bins=5)
            base_hist, _ = np.histogram(base[:, column], bins=bins)
            rec_hist, _ = np.histogram(rec[:, column], bins=bins)
            table = np.vstack([base_hist + 1, rec_hist + 1])
            try:
                _, p_value, _, _ = chi2_contingency(table)
            except ValueError:
                continue
            if p_value < 0.01:
                count += 1
        return count
