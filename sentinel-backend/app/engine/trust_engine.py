from __future__ import annotations


def severity_for_trust(score: float) -> str:
    if score < 35:
        return "CRITICAL"
    if score < 50:
        return "AT_RISK"
    if score < 70:
        return "WATCH"
    return "NORMAL"


def compute_penalty(anomaly: float, drift_factor: float, anomaly_threshold: float = 0.15) -> float:
    effective_anomaly = anomaly if anomaly >= anomaly_threshold else 0.0
    return 15.0 * ((effective_anomaly * drift_factor) ** 2)


def compute_recovery(anomaly: float, drift_confirmed: bool) -> float:
    return 0.0 if drift_confirmed else 0.3 * (1.0 - anomaly)


def drift_confirmed(*, adwin: bool, chi_squared: bool, model_disagreement: bool) -> bool:
    return sum([adwin, chi_squared, model_disagreement]) >= 2


def drift_factor(*, adwin: bool, chi_squared: bool, model_disagreement: bool) -> float:
    return min(2.0, 1.0 + (0.5 if adwin else 0.0) + (0.3 if chi_squared else 0.0) + (0.2 if model_disagreement else 0.0))


class TrustEngine:
    def __init__(self, initial_score: float = 95.0) -> None:
        self.score = float(initial_score)

    def update(self, anomaly: float, drift_factor: float, drifting: bool, policy_penalty: float) -> dict[str, float | bool | str]:
        effective_anomaly = anomaly if anomaly >= 0.15 else 0.0
        penalty = compute_penalty(anomaly, drift_factor)
        recovery = compute_recovery(anomaly, drifting)
        self.score = max(0.0, min(100.0, self.score - penalty - policy_penalty + recovery))
        return {
            "trust_score": round(self.score, 2),
            "severity": severity_for_trust(self.score),
            "anomaly_penalty": round(penalty, 4),
            "policy_penalty": round(policy_penalty, 4),
            "recovery": round(recovery, 4),
            "effective_anomaly": round(effective_anomaly * drift_factor, 4),
        }
