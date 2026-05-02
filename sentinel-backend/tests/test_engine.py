from __future__ import annotations

import pytest

from app.engine.trust_engine import TrustEngine, compute_penalty, compute_recovery, drift_confirmed, drift_factor, severity_for_trust


def test_penalty_formula_hand_calculated():
    assert compute_penalty(0.5, 1.0) == pytest.approx(3.75)
    assert compute_penalty(0.8, 2.0) == pytest.approx(38.4)


def test_recovery_only_when_not_drifting():
    assert compute_recovery(0.2, False) == pytest.approx(0.24)
    assert compute_recovery(0.2, True) == 0.0


def test_score_clamps_low_and_high():
    low = TrustEngine(initial_score=1)
    assert low.update(1.0, 2.0, True, 100)["trust_score"] == 0.0
    high = TrustEngine(initial_score=100)
    assert high.update(0.0, 1.0, False, 0)["trust_score"] == 100.0


@pytest.mark.parametrize("score,expected", [(100, "NORMAL"), (75, "NORMAL"), (65, "WATCH"), (45, "AT_RISK"), (20, "CRITICAL")])
def test_severity_mapping(score, expected):
    assert severity_for_trust(score) == expected


def test_drift_confirmation_requires_two_of_three():
    assert drift_confirmed(adwin=True, chi_squared=True, model_disagreement=False)
    assert not drift_confirmed(adwin=True, chi_squared=False, model_disagreement=False)


def test_drift_factor_components_and_cap():
    assert drift_factor(adwin=False, chi_squared=False, model_disagreement=False) == pytest.approx(1.0)
    assert drift_factor(adwin=True, chi_squared=True, model_disagreement=False) == pytest.approx(1.8)
    assert drift_factor(adwin=True, chi_squared=True, model_disagreement=True) == pytest.approx(2.0)


def test_below_anomaly_threshold_no_penalty_even_with_drift():
    engine = TrustEngine(initial_score=95)
    result = engine.update(0.14, 2.0, True, 0)
    assert result["anomaly_penalty"] == 0.0
    assert result["trust_score"] == 95.0
