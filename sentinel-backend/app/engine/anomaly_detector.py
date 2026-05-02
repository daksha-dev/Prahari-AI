from __future__ import annotations

from collections import deque

import numpy as np
from river.anomaly import HalfSpaceTrees
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from app.engine.feature_engineer import FEATURE_NAMES, mapping_from_vector


class AnomalyDetector:
    def __init__(self) -> None:
        self.scaler = StandardScaler()
        self.iforest = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
        self.hst = HalfSpaceTrees(n_trees=25, height=6, window_size=30, seed=42)
        self.trained = False
        self.if_min = 0.0
        self.if_scale = 1.0
        self.recent_scores: deque[float] = deque(maxlen=3)

    def train(self, burn_in: list[np.ndarray]) -> None:
        x = np.vstack(burn_in)
        scaled = self.scaler.fit_transform(x)
        self.iforest.fit(scaled)
        negated = -self.iforest.decision_function(scaled)
        self.if_min = float(negated.min())
        self.if_scale = float(max(negated.max() - negated.min(), 1e-6))
        for row in x:
            self.hst.learn_one(mapping_from_vector(row))
        self.trained = True

    def score(self, features: np.ndarray) -> dict[str, float]:
        if not self.trained:
            self.hst.learn_one(mapping_from_vector(features))
            return {"if_score": 0.0, "hst_score": 0.0, "combined_score": 0.0, "smoothed_score": 0.0}

        scaled = self.scaler.transform(np.asarray(features).reshape(1, -1))
        raw_if = float(self.iforest.decision_function(scaled)[0])
        if_score = float(np.clip((-raw_if - self.if_min) / self.if_scale, 0.0, 1.0))

        feature_dict = mapping_from_vector(features)
        raw_hst = float(self.hst.score_one(feature_dict) or 0.0)
        hst_score = float(np.clip(raw_hst / max(raw_hst + 0.5, 1e-6), 0.0, 1.0))
        self.hst.learn_one(feature_dict)

        combined = (0.6 * if_score) + (0.4 * hst_score)
        self.recent_scores.append(combined)
        smoothed = float(np.mean(self.recent_scores))
        return {
            "if_score": round(if_score, 4),
            "hst_score": round(hst_score, 4),
            "combined_score": round(combined, 4),
            "smoothed_score": round(smoothed, 4),
        }


def feature_names() -> list[str]:
    return list(FEATURE_NAMES)
