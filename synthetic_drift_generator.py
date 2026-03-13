"""
synthetic_drift_generator.py - IoT Trust & Drift Analytics System

Generates synthetic slow-drift scenarios to validate drift detection signals
(ADWIN, Chi-Squared, Model Disagreement) on controlled, known-good data.

Why synthetic data?
-------------------
The CICIoT2023 dataset has *hard transitions* (benign -> attack in one window).
This exercises anomaly detection well but is too abrupt to reliably trigger
ADWIN (which detects gradual mean shift) and Model Disagreement (which relies
on the adaptive HST being "poisoned" before the static IF notices).

These synthetic scenarios use *linear interpolation* over 50 windows so
that the drift is gradual enough for all three signals to observe a real
distributional change unfolding over time.

Scenario overview
-----------------
1. Camera Reconnaissance  -- unique destinations and port diversity grow slowly
                             as the camera starts scanning the network.
2. Thermostat DDoS        -- traffic volume and burstiness ramp up as the
                             device is recruited into a botnet.
3. Smart Lock Brute Force -- connection failures and SYN/RST counts creep up
                             as the device attempts credential stuffing.

Attack feature construction
---------------------------
Instead of simply multiplying the benign *mean* (which the Isolation Forest
sees as perfectly normal), the attack endpoint is computed as:

    attack[i] = mean[i] + k * std[i]

where *k* is an aggressive multiplier (10-20 sigma).  This ensures the attack
features are genuinely outside the training distribution's boundaries, not
just scaled versions of the centroid.

When no ``burn_in_std`` is supplied (backward compat), the function falls
back to multiplying the mean by a large factor.
"""

import numpy as np
from typing import Dict, List, Optional

from feature_engineer import FEATURE_NAMES


# -- Feature index map --------------------------------------------------------
# Pre-compute indices once so the scaling code is readable and fast.

_IDX = {name: i for i, name in enumerate(FEATURE_NAMES)}


# -- Core interpolation primitive ----------------------------------------------


def generate_slow_drift(
    benign_features: np.ndarray,
    attack_features: np.ndarray,
    n_windows: int = 50,
) -> List[np.ndarray]:
    """
    Linearly interpolate from benign behaviour to attack behaviour over
    *n_windows* time steps.

    Each output vector at position *i* is:

        blended[i] = benign * (1 - alpha) + attack * alpha
        alpha = i / (n_windows - 1)        # 0.0 -> 1.0

    So the first window is 100 % benign and the last is 100 % attack.
    Intermediate windows are weighted blends, simulating a device that
    gradually shifts its behaviour rather than switching abruptly.

    Parameters
    ----------
    benign_features : np.ndarray
        Shape ``(22,)`` -- average feature vector during normal operation.
    attack_features : np.ndarray
        Shape ``(22,)`` -- target feature vector at full compromise.
    n_windows : int
        Number of windows in the drift sequence (default 50).

    Returns
    -------
    list of np.ndarray
        Length *n_windows*.  Each element is a ``(22,)`` float array.
        Index 0 equals *benign_features*; index -1 equals *attack_features*.

    Example
    -------
    >>> drift = generate_slow_drift(benign, attack, n_windows=5)
    >>> # alpha values: 0.00, 0.25, 0.50, 0.75, 1.00
    """
    if n_windows < 2:
        raise ValueError("n_windows must be >= 2")

    benign = benign_features.astype(float)
    attack = attack_features.astype(float)

    alphas = np.linspace(0.0, 1.0, n_windows)
    return [benign * (1.0 - a) + attack * a for a in alphas]


def _build_attack_vector(
    mean: np.ndarray,
    std: Optional[np.ndarray],
    feature_sigmas: Dict[str, float],
    feature_multipliers: Dict[str, float],
) -> np.ndarray:
    """
    Build an attack feature vector by pushing selected features far outside
    the burn-in distribution.

    For each target feature, the attack value is computed as:
        - If ``std`` is available:  mean + sigma_k * std   (pushes k sigma out)
        - Else:                     mean * multiplier       (fallback scaling)

    The ``std`` is clipped to at least ``0.01 * abs(mean)`` so that features
    with zero variance still get pushed.

    Parameters
    ----------
    mean : np.ndarray
        Shape (22,) -- burn-in feature means.
    std : np.ndarray or None
        Shape (22,) -- burn-in feature standard deviations.
    feature_sigmas : dict
        Feature name -> number of sigma to push (used when std is available).
    feature_multipliers : dict
        Feature name -> multiplier on mean (fallback when std is None).

    Returns
    -------
    np.ndarray shape (22,)
    """
    attack = mean.copy().astype(float)

    for feat_name, sigma_k in feature_sigmas.items():
        idx = _IDX[feat_name]
        if std is not None:
            # Ensure minimum std so zero-variance features still shift
            effective_std = max(std[idx], 0.01 * abs(mean[idx]) + 1e-6)
            attack[idx] = mean[idx] + sigma_k * effective_std
        else:
            mult = feature_multipliers.get(feat_name, sigma_k)
            attack[idx] = mean[idx] * mult

    return attack


# -- Scenario 1: Camera Reconnaissance ----------------------------------------


def create_camera_recon_drift(
    benign_features: np.ndarray,
    n_windows: int = 50,
    burn_in_std: Optional[np.ndarray] = None,
) -> List[np.ndarray]:
    """
    Simulate an IP camera slowly pivoting to network reconnaissance.

    A compromised camera will begin probing other devices on the network:
    it contacts many unique destination IPs (port scanning), tries a wide
    variety of ports (increasing port entropy), and contacts destinations
    not seen during normal operation (new_dst_count).

    Feature offsets (sigma from mean)
    ---------------------------------
    - ``unique_dst_ips``  +20 sigma  -- device contacts far more unique hosts
    - ``port_entropy``    +15 sigma  -- port diversity jumps (random scanning)
    - ``new_dst_count``   +20 sigma  -- many new previously-unseen destinations
    - ``packets_per_sec`` +10 sigma  -- correlated traffic increase
    - ``bytes_per_sec``   +8 sigma   -- more data from probe responses

    Fallback multipliers (when std unavailable): 50x, 30x, 40x, 8x, 5x.
    """
    sigmas = {
        "unique_dst_ips": 20.0,
        "port_entropy": 15.0,
        "new_dst_count": 20.0,
        "packets_per_sec": 10.0,
        "bytes_per_sec": 8.0,
    }
    mults = {
        "unique_dst_ips": 50.0,
        "port_entropy": 30.0,
        "new_dst_count": 40.0,
        "packets_per_sec": 8.0,
        "bytes_per_sec": 5.0,
    }
    attack = _build_attack_vector(benign_features, burn_in_std, sigmas, mults)
    return generate_slow_drift(benign_features, attack, n_windows)


# -- Scenario 2: Thermostat DDoS ----------------------------------------------


def create_thermostat_ddos_drift(
    benign_features: np.ndarray,
    n_windows: int = 50,
    burn_in_std: Optional[np.ndarray] = None,
) -> List[np.ndarray]:
    """
    Simulate a smart thermostat slowly joining a DDoS botnet.

    Once recruited, the thermostat begins flooding a target with traffic.
    The total bytes and packets per second increase dramatically, and the
    traffic becomes bursty (irregular packet timing typical of attack tools).

    Feature offsets (sigma from mean)
    ---------------------------------
    - ``bytes_per_sec``      +25 sigma  -- massive bandwidth spike
    - ``packets_per_sec``    +25 sigma  -- rapid-fire packet generation
    - ``burstiness``         +20 sigma  -- highly irregular burst pattern
    - ``syn_ack_ratio``      +15 sigma  -- many incomplete connections
    - ``avg_payload_size``   -15 sigma  -- small attack packets (amplification)

    Fallback multipliers: 100x, 80x, 50x, 10x, 0.1x.
    """
    sigmas = {
        "bytes_per_sec": 25.0,
        "packets_per_sec": 25.0,
        "burstiness": 20.0,
        "syn_ack_ratio": 15.0,
    }
    mults = {
        "bytes_per_sec": 100.0,
        "packets_per_sec": 80.0,
        "burstiness": 50.0,
        "syn_ack_ratio": 10.0,
    }
    attack = _build_attack_vector(benign_features, burn_in_std, sigmas, mults)

    # avg_payload_size decreases (small flood packets) -- handle specially
    idx = _IDX["avg_payload_size"]
    if burn_in_std is not None:
        effective_std = max(burn_in_std[idx], 0.01 * abs(benign_features[idx]) + 1e-6)
        attack[idx] = max(benign_features[idx] - 15.0 * effective_std, 0.0)
    else:
        attack[idx] = benign_features[idx] * 0.1

    return generate_slow_drift(benign_features, attack, n_windows)


# -- Scenario 3: Smart Lock Brute Force ---------------------------------------


def create_smartlock_bruteforce_drift(
    benign_features: np.ndarray,
    n_windows: int = 50,
    burn_in_std: Optional[np.ndarray] = None,
) -> List[np.ndarray]:
    """
    Simulate a smart lock slowly performing credential brute-forcing.

    A compromised smart lock will repeatedly attempt to authenticate to
    other devices.  Most attempts fail (high connection failure rate and
    RST count), and the SYN/ACK ratio rises because connections are
    initiated but rarely completed (many SYNs, few ACKs).

    Feature offsets (sigma from mean)
    ---------------------------------
    - ``connection_failure_rate`` +20 sigma  -- most connections fail
    - ``syn_ack_ratio``          +20 sigma   -- many incomplete connections
    - ``rst_rate``               +20 sigma   -- connections torn down
    - ``packets_per_sec``        +15 sigma   -- rapid connection attempts
    - ``unique_dst_ips``         +10 sigma   -- targeting multiple hosts

    Fallback multipliers: 60x, 40x, 50x, 15x, 10x.
    """
    sigmas = {
        "connection_failure_rate": 20.0,
        "syn_ack_ratio": 20.0,
        "rst_rate": 20.0,
        "packets_per_sec": 15.0,
        "unique_dst_ips": 10.0,
    }
    mults = {
        "connection_failure_rate": 60.0,
        "syn_ack_ratio": 40.0,
        "rst_rate": 50.0,
        "packets_per_sec": 15.0,
        "unique_dst_ips": 10.0,
    }
    attack = _build_attack_vector(benign_features, burn_in_std, sigmas, mults)
    return generate_slow_drift(benign_features, attack, n_windows)


# -- Scenario 4: Frozen Sensor (Spoofed/Compromised) --------------------------


def generate_frozen_sensor_windows(n_windows: int = 80) -> List[np.ndarray]:
    """
    Simulate a sensor that is frozen or spoofed, returning the exact same
    feature values continuously. This triggers the 'flatness' drift drift.
    
    Parameters
    ----------
    n_windows : int
        Number of frozen windows to generate.
        
    Returns
    -------
    list of np.ndarray
        Length *n_windows*. Each element is an identical ``(22,)`` float array.
    """
    # Create a typical benign-looking non-zero baseline
    frozen = np.zeros(22, dtype=float)
    frozen[0] = 100.0  # just some traffic so it's not all zeros initially
    frozen[1] = 50.0
    
    return [frozen.copy() for _ in range(n_windows)]


# -- Convenience wrapper -------------------------------------------------------


def create_all_drift_scenarios(
    benign_features: np.ndarray,
    n_windows: int = 50,
    burn_in_std: Optional[np.ndarray] = None,
) -> Dict[str, List[np.ndarray]]:
    """
    Generate all three synthetic drift scenarios from a single benign baseline.

    Parameters
    ----------
    benign_features : np.ndarray
        Shape ``(22,)`` -- average feature vector during normal operation.
        Typically computed as ``np.mean(burn_in_feature_matrix, axis=0)``.
    n_windows : int
        Number of monitoring windows per scenario (default 50).
    burn_in_std : np.ndarray or None
        Shape ``(22,)`` -- standard deviation of each feature over burn-in.
        When provided, attack vectors are placed at k-sigma offsets from
        the mean rather than simple multipliers, producing more realistic
        anomaly scores.

    Returns
    -------
    dict
        Keys: ``'camera_recon'``, ``'thermostat_ddos'``, ``'smartlock_bruteforce'``
        Values: list of *n_windows* numpy arrays of shape ``(22,)``

    Example
    -------
    >>> scenarios = create_all_drift_scenarios(benign_avg, n_windows=50,
    ...                                       burn_in_std=benign_std)
    >>> for name, sequence in scenarios.items():
    ...     print(f"{name}: {len(sequence)} windows")
    camera_recon: 50 windows
    thermostat_ddos: 50 windows
    smartlock_bruteforce: 50 windows
    """
    return {
        "camera_recon": create_camera_recon_drift(
            benign_features, n_windows, burn_in_std
        ),
        "thermostat_ddos": create_thermostat_ddos_drift(
            benign_features, n_windows, burn_in_std
        ),
        "smartlock_bruteforce": create_smartlock_bruteforce_drift(
            benign_features, n_windows, burn_in_std
        ),
    }


# -- Smoke test ----------------------------------------------------------------

if __name__ == "__main__":
    print("=== Synthetic Drift Generator smoke test ===\n")

    # Simulated benign baseline: small non-zero values typical of a quiet IoT device
    rng = np.random.default_rng(42)
    benign = rng.uniform(0.01, 1.0, size=22)
    std = rng.uniform(0.001, 0.1, size=22)

    scenarios = create_all_drift_scenarios(benign, n_windows=50, burn_in_std=std)

    for name, seq in scenarios.items():
        assert len(seq) == 50, f"{name}: expected 50 windows, got {len(seq)}"
        assert seq[0].shape == (22,), f"{name}: expected shape (22,)"
        # First window should equal benign
        assert np.allclose(seq[0], benign), f"{name}: first window should match benign"
        print(f"[PASS] {name}: {len(seq)} windows, shape {seq[0].shape}")
        # Show which features changed at full attack (last window)
        changed = [(FEATURE_NAMES[i], seq[-1][i] / benign[i])
                    for i in range(22) if not np.isclose(seq[-1][i], benign[i])]
        for feat, ratio in changed:
            print(f"       {feat}: {ratio:.1f}x at full attack")
        print()

    # Also test without std (backward compat)
    scenarios2 = create_all_drift_scenarios(benign, n_windows=10)
    for name, seq in scenarios2.items():
        assert len(seq) == 10
        print(f"[PASS] {name} (no std): {len(seq)} windows")

    print("\nAll smoke tests passed.")
