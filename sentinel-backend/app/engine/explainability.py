from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from app.engine.feature_engineer import FEATURE_NAMES, z_scores


def evidence_card(
    *,
    features: np.ndarray,
    baseline_mean: np.ndarray,
    baseline_std: np.ndarray,
    drift: dict,
    policy_violations: list,
    anomaly: dict,
    window_id: int,
) -> dict:
    z = z_scores(features, baseline_mean, baseline_std)
    ranked = sorted(
        [{"name": FEATURE_NAMES[i], "z_score": round(float(abs(score)), 3)} for i, score in enumerate(z)],
        key=lambda item: item["z_score"],
        reverse=True,
    )[:5]
    policy_feature_names = {getattr(violation, "rule", "") for violation in policy_violations}
    insert_at = len(ranked) - 1
    for feature_name in sorted(policy_feature_names):
        if feature_name in FEATURE_NAMES and all(item["name"] != feature_name for item in ranked):
            index = FEATURE_NAMES.index(feature_name)
            ranked[insert_at] = {"name": feature_name, "z_score": round(float(abs(z[index])), 3)}
            insert_at = max(0, insert_at - 1)
    return {
        "top_deviating_features": ranked,
        "drift_signals_fired": list(drift.get("fired", [])),
        "policy_violations": [violation.__dict__ for violation in policy_violations],
        "raw_anomaly_score": float(anomaly.get("combined_score", 0.0)),
        "smoothed_score": float(anomaly.get("smoothed_score", 0.0)),
        "window_id": window_id,
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
    }


def synthesize_evidence_explanation(evidence: dict) -> str:
    features = evidence.get("top_deviating_features", [])[:3]
    signals = evidence.get("drift_signals_fired", [])
    policies = evidence.get("policy_violations", [])
    feature_text = ", ".join(f"{item.get('name')} at z-score {item.get('z_score')}" for item in features) or "no major feature deviations"
    signal_text = ", ".join(signals) if signals else "no formal drift signal"
    policy_text = policies[0].get("detail") if policies else "no hard policy rule fired"
    return (
        f"The latest window is unusual because {feature_text} moved farthest away from the device baseline. "
        f"Drift evidence shows {signal_text}, while policy checks report {policy_text}. "
        "Together, this suggests the device behavior should be reviewed before it is trusted again."
    )
