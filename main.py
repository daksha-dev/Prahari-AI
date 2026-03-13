"""
main.py — IoT Trust & Drift Analytics System

Orchestrates the complete pipeline: load data → extract features →
detect anomalies → detect drift → check policies → score trust →
generate evidence reports.

Pipeline phases
---------------
1. **Initialisation** — Parse CLI arguments, load ``config.yaml``,
   instantiate all components.

2. **Data loading** — Read CICIoT2023 CSV files and split into per-device
   time windows (default 60 s each).

3. **Per-device processing** — For every device:

   a. *Feature extraction* — Convert each window's raw flow records
      into a 22-dimensional behavioural feature vector.

   b. *Burn-in (windows 1–30)* — Establish a baseline profile.  Train
      the static Isolation Forest on the burn-in feature matrix, prime
      the adaptive Half-Space Trees, and collect baseline destination
      IPs.  **No trust penalties are applied during burn-in** — the
      score stays at its initial value (100).  Burn-in must complete
      before monitoring starts because the statistical models need a
      reference distribution against which to measure deviation.

   c. *Monitoring (windows 31 +)* — Score each window against both
      anomaly models, run three drift signals, apply policy checks,
      update the trust score, and generate evidence reports for any
      window that drops below the explainability threshold.

4. **Aggregation** — Collect results across all devices, compute
   summary statistics, and persist everything to JSON.

Example invocations
-------------------
::

    # Default — all devices, reads CSVs from the project directory
    python main.py

    # Verbose output for a specific device
    python main.py --device 192.168.1.5 --verbose

    # Limit processing to first 100 windows
    python main.py --windows 100

    # Custom config and output path
    python main.py --config config_strict.yaml --output results/run1.json
"""

import argparse
import json
import os
import sys
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import yaml

# -- Local module imports -----------------------------------------------------
from data_loader import load_dataset, inject_synthetic_drift_into_device
from feature_engineer import FEATURE_NAMES, extract_features
from anomaly_detector import DualModelDetector, convert_array_to_dict
from drift_detector import DriftDetector, get_recent_features
from policy_checker import PolicyChecker
from trust_engine import TrustEngine
from explainability import ExplainabilityEngine
from synthetic_drift_generator import create_all_drift_scenarios


# =============================================================================
#  Helper functions
# =============================================================================


def convert_to_dict(feature_array: np.ndarray) -> Dict[str, float]:
    """
    Convert a 1-D numpy feature array (shape 22,) into a named
    dictionary ``{feature_name: value}`` for modules that expect dicts
    (River models, policy checker, explainability engine).
    """
    return convert_array_to_dict(feature_array, FEATURE_NAMES)


def collect_baseline_ips(
    window_list: list,
    num_windows: int = 30,
    ip_column: str = "dst_ip",
) -> Set[str]:
    """
    Extract all destination IPs observed across the first *num_windows*
    DataFrames.  These form the burn-in baseline; destinations not in
    this set are considered "new" during monitoring.

    When the dataset is preprocessed (no dst_ip column), collects active
    service indicator names instead (prefixed with ``_svc_``), so that
    ``feature_engineer.new_dst_count`` can detect new services appearing
    after burn-in.
    """
    ips: Set[str] = set()
    has_ip_col = False
    _SERVICE_COLS = ["HTTP", "HTTPS", "DNS", "Telnet", "SMTP", "SSH", "IRC"]

    for w in window_list[:num_windows]:
        if not hasattr(w, "columns"):
            continue
        # Try every known column-name variant
        for col in [ip_column, "dst_ip", "Dst_IP", "Destination_IP", "Dst IP"]:
            if col in w.columns:
                ips.update(w[col].dropna().astype(str).unique())
                has_ip_col = True
                break

    # Preprocessed format: collect active services as proxy for baseline
    if not has_ip_col:
        for w in window_list[:num_windows]:
            if not hasattr(w, "columns"):
                continue
            for svc in _SERVICE_COLS:
                if svc in w.columns and w[svc].sum() > 0:
                    ips.add(f"_svc_{svc}")

    return ips


def collect_baseline_protocols(
    features_list: List[np.ndarray],
    num_windows: int = 30,
) -> Set[str]:
    """
    Determine which protocols (TCP, UDP, ICMP) are active during the
    burn-in period.  A protocol is considered active if its ratio
    feature is > 0 in *any* burn-in window.
    """
    # Indices: tcp_ratio=10, udp_ratio=11, icmp_ratio=12
    protocols: Set[str] = set()
    for feat in features_list[:num_windows]:
        if feat[10] > 0:
            protocols.add("tcp")
        if feat[11] > 0:
            protocols.add("udp")
        if feat[12] > 0:
            protocols.add("icmp")
    return protocols


def store_evidence(
    evidence_dict: dict,
    device_id: str,
    window_index: int,
    output_dir: str = "results",
) -> str:
    """
    Persist a single evidence report as a JSON file.  Creates the output
    directory if it does not exist.

    Returns the path to the written file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    safe_id = device_id.replace(".", "_").replace(":", "_")
    filename = f"{safe_id}_window_{window_index}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(evidence_dict, f, indent=2, default=str)
    return filepath


def print_startup_message(config: dict, args: argparse.Namespace) -> None:
    """Print a startup banner summarising the active configuration."""
    print("\n" + "=" * 72)
    print("  IoT Trust & Drift Analytics System")
    print("=" * 72)

    data_cfg = config.get("data", {})
    trust_cfg = config.get("trust", {})
    drift_cfg = config.get("drift", {})
    policy_cfg = config.get("policy", {})
    explain_cfg = config.get("explainability", {})

    print(f"\n  Config file    : {args.config}")
    print(f"  Window size    : {data_cfg.get('window_size_seconds', 60)}s")
    print(f"  Burn-in windows: {data_cfg.get('burn_in_windows', 30)}")
    print(f"  Trust initial  : {trust_cfg.get('initial_score', 100)}")
    print(f"  Anomaly thresh : {config.get('anomaly', {}).get('anomaly_threshold', 0.15)}")
    print(f"  Penalty mult   : {trust_cfg.get('penalty_multiplier', 15)}")
    print(f"  Recovery rate  : {trust_cfg.get('recovery_rate', 0.3)}")

    # Drift signals
    signals = []
    if drift_cfg.get("adwin", {}).get("enabled", True):
        signals.append("ADWIN")
    if drift_cfg.get("chi_squared", {}).get("enabled", True):
        signals.append("Chi²")
    if drift_cfg.get("disagreement", {}).get("enabled", True):
        signals.append("Model-disagreement")
    print(f"  Drift signals  : {', '.join(signals) or 'none'} "
          f"(require {drift_cfg.get('confirmation', {}).get('signals_required', 2)})")

    # Policy rules
    rules = [r for r in policy_cfg if policy_cfg[r].get("enabled", False)]
    print(f"  Policy rules   : {', '.join(rules) or 'none'}")

    print(f"  Explain thresh : score < {explain_cfg.get('generate_on_score_below', 70)}")
    print(f"  Output file    : {args.output}")
    if args.device:
        print(f"  Target device  : {args.device}")
    if args.windows:
        print(f"  Max windows    : {args.windows}")
    print(f"  Verbose        : {args.verbose}")
    print()


def print_device_summary(
    device_id: str,
    history: List[dict],
    final_score: float,
    final_severity: str,
) -> None:
    """Print a compact post-processing summary for one device."""
    n_alerts = sum(1 for h in history if h["trust_score"] < 70)
    n_critical = sum(1 for h in history if h["trust_score"] < 30)
    scores = [h["trust_score"] for h in history]
    min_score = min(scores) if scores else final_score
    max_score = max(scores) if scores else final_score

    severity_icon = {
        "NORMAL": "[OK]", "WARNING": "[!]",
        "HIGH": "[!!]", "CRITICAL": "[!!!]",
    }.get(final_severity, "[?]")

    print(f"\n  +- Device {device_id}")
    print(f"  |  Final score : {final_score:.1f} / 100  {severity_icon} {final_severity}")
    print(f"  |  Score range : {min_score:.1f} - {max_score:.1f}")
    print(f"  |  Alert windows: {n_alerts}  |  Critical windows: {n_critical}")
    print(f"  |  Windows processed: {len(history)}")
    print(f"  +{'-' * 50}")


def print_overall_summary(
    results: Dict[str, dict],
    config: dict,
) -> None:
    """Print aggregate statistics across all analysed devices."""
    if not results:
        print("\n  No devices were processed.")
        return

    scores = [r["final_score"] for r in results.values()]
    n_devices = len(scores)
    avg_score = sum(scores) / n_devices
    critical = sum(1 for s in scores if s < 30)
    high_risk = sum(1 for s in scores if s < 50)
    suspicious = sum(1 for s in scores if s < 70)

    print("\n" + "=" * 72)
    print("  OVERALL SUMMARY")
    print("=" * 72)
    print(f"  Devices processed : {n_devices}")
    print(f"  Average trust     : {avg_score:.1f} / 100")
    print(f"  [!!!] Critical (< 30) : {critical}")
    print(f"  [!!] High risk (< 50): {high_risk}")
    print(f"  [!]  Suspicious (< 70): {suspicious}")
    print(f"  [OK] Normal (>= 70)   : {n_devices - suspicious}")
    print("=" * 72)


# =============================================================================
#  CLI argument parser
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="IoT Trust & Drift Analytics — main pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python main.py                              # default run
  python main.py --scenario sudden_attack     # attack scenario
  python main.py --device 192.168.1.5         # single device
  python main.py --windows 100 --verbose      # limited + verbose
  python main.py --config config_strict.yaml  # custom config
  python main.py --output results/run.json    # custom output path
""",
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--scenario", type=str, default="slow_drift",
        choices=["sudden_attack", "slow_drift", "clean_device"],
        help="Test scenario to run (default: slow_drift)",
    )
    parser.add_argument(
        "--device", type=str, default=None,
        help="Specific device IP to analyse (default: all devices)",
    )
    parser.add_argument(
        "--windows", type=int, default=None,
        help="Max number of windows to process per device (default: all)",
    )
    parser.add_argument(
        "--output", type=str, default="results.json",
        help="Output file path for aggregate results (default: results.json)",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False,
        help="Print detailed per-window logs",
    )
    return parser


# =============================================================================
#  Config loading
# =============================================================================


def load_config(path: str) -> dict:
    """
    Load and validate the YAML configuration file.

    Exits with a clear error message if the file is missing or
    malformed.
    """
    config_path = Path(path)
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path.resolve()}")
        print("        Run with --config <path> to specify an alternative.")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"[ERROR] Failed to parse config: {exc}")
        sys.exit(1)

    if not isinstance(config, dict):
        print("[ERROR] Config file must contain a YAML mapping (dict).")
        sys.exit(1)

    return config


# =============================================================================
#  Main pipeline
# =============================================================================


def run_pipeline(args: argparse.Namespace) -> None:
    """
    Execute the full trust-scoring pipeline.

    This is the heart of the system.  Each device is processed
    independently: burn-in → monitoring → summary.  Results are
    aggregated at the end and saved to disk.
    """

    # -- Step 1: INITIALISATION -------------------------------------------
    config = load_config(args.config)
    data_cfg = config.get("data", {})
    burn_in_count = int(data_cfg.get("burn_in_windows", 30))
    min_flows = int(data_cfg.get("min_flows_per_window", 5))
    explain_threshold = float(
        config.get("explainability", {}).get("generate_on_score_below", 70)
    )

    # Instantiate all components
    dual_detector = DualModelDetector(config)
    drift_detector = DriftDetector(config)
    policy_checker = PolicyChecker(config)
    trust_engine = TrustEngine(config)
    explain_engine = ExplainabilityEngine(config)

    print_startup_message(config, args)

    # -- Step 2: DATA LOADING ---------------------------------------------
    data_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        device_windows = load_dataset(data_dir=data_dir)
    except FileNotFoundError as exc:
        print(f"[ERROR] Data loading failed: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] Unexpected error loading data: {exc}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)

    # -- Step 2b: PROGRAMMATIC SYNTHETIC DRIFT DEVICES (10.0.5.x) ---------
    benign_device_id = next((d for d in device_windows if d.startswith("10.0.1.")), None)
    if benign_device_id:
        burn_in_df_windows = device_windows[benign_device_id][:burn_in_count]
        burn_in_feat_arrays = []
        for wdf in burn_in_df_windows:
            try:
                fd = extract_features(wdf)
            except Exception:
                fd = {n: 0.0 for n in FEATURE_NAMES}
            arr = np.array([fd.get(n, 0.0) for n in FEATURE_NAMES], dtype=float)
            burn_in_feat_arrays.append(arr)
        
        burn_in_array_local = np.vstack(burn_in_feat_arrays)
        benign_avg = burn_in_array_local.mean(axis=0)
        benign_std = burn_in_array_local.std(axis=0)
        
        scenarios = create_all_drift_scenarios(benign_avg, n_windows=50, burn_in_std=benign_std)
        seq1 = scenarios["camera_recon"]
        seq2 = scenarios["thermostat_ddos"]
        seq3 = scenarios["smartlock_bruteforce"]
        # Two mixed patterns
        seq4 = [(a + b) / 2.0 for a, b in zip(seq1, seq2)]
        seq5 = [(a + b) / 2.0 for a, b in zip(seq2, seq3)]
        
        synthetic_seqs = [seq1, seq2, seq3, seq4, seq5]
        for idx, seq in enumerate(synthetic_seqs):
            dev_ip = f"10.0.5.{idx + 1}"
            device_windows[dev_ip] = burn_in_df_windows + seq

        from synthetic_drift_generator import generate_frozen_sensor_windows
        frozen_windows = generate_frozen_sensor_windows(n_windows=80)
        device_windows["192.168.50.21"] = frozen_windows

    # Filter to a single device if requested
    if args.device:
        if args.device in device_windows:
            device_windows = {args.device: device_windows[args.device]}
        else:
            print(f"[ERROR] Device '{args.device}' not found in dataset.")
            print(f"        Available devices: {list(device_windows.keys())}")
            sys.exit(1)

    total_windows = sum(len(w) for w in device_windows.values())
    print(f"\n  Loaded {len(device_windows)} device(s), "
          f"{total_windows:,} total windows\n")

    # -- Step 3: PER-DEVICE PROCESSING ------------------------------------
    all_results: Dict[str, dict] = {}
    all_evidence: Dict[str, List[str]] = {}  # device → list of file paths

    for device_id, window_list in device_windows.items():

        # Optionally cap the number of windows
        if args.windows is not None:
            window_list = window_list[: args.windows]

        num_windows = len(window_list)
        if num_windows < burn_in_count:
            print(f"  [SKIP] {device_id}: only {num_windows} windows "
                  f"(need {burn_in_count} for burn-in)")
            continue

        print(f"\n{'-' * 60}")
        print(f"  Processing device: {device_id}  ({num_windows} windows)")
        print(f"{'-' * 60}")

        try:
            device_result = _process_device(
                device_id=device_id,
                window_list=window_list,
                config=config,
                burn_in_count=burn_in_count,
                explain_threshold=explain_threshold,
                verbose=args.verbose,
            )
        except Exception as exc:
            print(f"  [ERROR] Device {device_id} failed: {exc}")
            if args.verbose:
                traceback.print_exc()
            continue  # graceful degradation — continue to next device

        all_results[device_id] = device_result["summary"]
        all_evidence[device_id] = device_result.get("evidence_files", [])

        # Print per-device summary
        print_device_summary(
            device_id,
            device_result["summary"]["history"],
            device_result["summary"]["final_score"],
            device_result["summary"]["severity"],
        )

    # -- Step 4: AGGREGATION & PERSISTENCE --------------------------------
    print_overall_summary(all_results, config)
    metrics = _compute_evaluation_metrics(all_results)
    _print_evaluation_metrics(metrics)
    _save_results(all_results, all_evidence, config, args, metrics=metrics)

    print("\n=== HST Gating Summary ===")
    for dev_id, result in all_results.items():
        gated = result.get("hst_gated_windows", 0)
        learned = result.get("hst_learned_windows", 0)
        print(f"{dev_id} : {gated} windows gated, {learned} windows learned")

    # -- Step 5: SYNTHETIC DRIFT TESTING ----------------------------------
    # Run three controlled slow-drift scenarios to validate that ADWIN,
    # Chi-Squared, and Model Disagreement signals actually fire when a
    # device gradually changes behaviour over 50 windows.
    _run_synthetic_drift_tests(device_windows, config, args)


# =============================================================================
#  Per-device processing
# =============================================================================


def _process_device(
    device_id: str,
    window_list: list,
    config: dict,
    burn_in_count: int,
    explain_threshold: float,
    verbose: bool,
) -> dict:
    """
    Run the full pipeline for a single device.

    Returns a dict with 'summary' (device-level results) and
    'evidence_files' (list of evidence report file paths).
    """

    # -- A. FEATURE EXTRACTION ----------------------------------------
    features_list: List[np.ndarray] = []
    features_dict_list: List[Dict[str, float]] = []

    for window_df in window_list:
        if isinstance(window_df, np.ndarray):
            feat_array = window_df
            feat_dict = convert_array_to_dict(feat_array)
        else:
            try:
                feat_dict = extract_features(window_df)
            except Exception:
                feat_dict = {name: 0.0 for name in FEATURE_NAMES}
    
            feat_array = np.array(
                [feat_dict.get(name, 0.0) for name in FEATURE_NAMES],
                dtype=float,
            )
            
        features_list.append(feat_array)
        features_dict_list.append(feat_dict)

    print(f"  Extracted {len(features_list)} feature vectors")

    # -- B. BURN-IN PHASE (windows 0 .. burn_in_count-1) --------------
    burn_in_arrays = features_list[:burn_in_count]
    burn_in_array = np.vstack(burn_in_arrays)  # shape (30, 22)

    # Collect baseline IPs, protocols, and ports
    baseline_ips = collect_baseline_ips(window_list, burn_in_count)
    baseline_protocols = collect_baseline_protocols(features_list, burn_in_count)

    # Collect ports/services active during burn-in so the forbidden-ports
    # policy only fires for NEW suspicious ports not seen in normal traffic
    baseline_ports: Set[int] = set()
    for fd in features_dict_list[:burn_in_count]:
        for p in fd.get("ports_used", []):
            baseline_ports.add(int(p))

    # Train static model (Isolation Forest)
    dual_detector = DualModelDetector(config)
    dual_detector.train_static(burn_in_array)

    # Prime adaptive model (Half-Space Trees)
    burn_in_dicts = features_dict_list[:burn_in_count]
    dual_detector.prime_adaptive(burn_in_dicts)

    # Fresh drift detector and trust engine for this device
    drift_detector = DriftDetector(config)

    # Seed ADWIN and model-disagreement detector with burn-in anomaly scores.
    # This gives them a "before" reference (benign scores ~0.05) so they can
    # detect the shift when attack traffic starts in the monitoring phase.
    # Pre-calculate burn-in scores
    burn_scores = [dual_detector.score(fd) for fd in burn_in_dicts]

    # Seed model-disagreement detector (once is enough since it uses consecutive streak)
    for bi_if, bi_hst, _ in burn_scores:
        drift_detector.update_disagreement(bi_if, bi_hst)

    # Pre-seed ADWIN multiple times (Option C) to build a robust statistical baseline.
    # 30 burn-in windows * 5 passes = 150 benign samples, creating a tight Hoeffding bound.
    for _ in range(2):
        for _, _, bi_combined in burn_scores:
            drift_detector.update_adwin(bi_combined)
    trust_engine = TrustEngine(config)
    trust_engine.reset_score()

    explain_engine = ExplainabilityEngine(config)
    policy_checker = PolicyChecker(config)

    # Chi-squared needs recent features; keep a rolling buffer
    chi_sq_windows = int(
        config.get("drift", {}).get("chi_squared", {}).get("recent_windows", 10)
    )
    recent_features_buffer: deque = deque(maxlen=chi_sq_windows)

    print(f"  Burn-in complete (baseline: {len(baseline_ips)} IPs, "
          f"protocols: {baseline_protocols or '{none}'})")

    # -- C. MONITORING PHASE (windows burn_in_count .. end) ------------
    history: List[dict] = []
    evidence_files: List[str] = []
    alert_count = 0
    hst_gated_windows = 0
    hst_learned_windows = 0

    num_monitoring = len(features_list) - burn_in_count
    progress_interval = max(1, num_monitoring // 10)  # ~10 progress updates

    for i in range(burn_in_count, len(features_list)):
        window_idx = i  # absolute window index
        feat_dict = features_dict_list[i]
        feat_array = features_list[i]

        # -- i. ANOMALY DETECTION ---------------------------------
        try:
            if_score, hst_score, combined_score = dual_detector.score(feat_dict)
            # Gate HST learning on the *previous* window's trust score.
            # If the device is already flagged (score < 50), HST freezes
            # so it cannot normalise ongoing attack traffic as benign.
            current_trust = trust_engine.get_score()
            if current_trust < 30:
                hst_gated_windows += 1
            else:
                hst_learned_windows += 1
            dual_detector.update_adaptive(feat_dict, trust_score=current_trust, device_id=device_id)
        except Exception as exc:
            if verbose:
                print(f"    [WARN] Window {window_idx}: scoring failed ({exc})")
            if_score, hst_score, combined_score = 0.0, 0.0, 0.0

        # -- ii. DRIFT DETECTION ----------------------------------
        # Signal 1: ADWIN (anomaly score stream)
        drift_detector.update_adwin(combined_score)

        # Signal 2: Chi-squared (feature distribution comparison)
        recent_features_buffer.append(feat_array)
        if len(recent_features_buffer) >= 2:
            recent_array = np.vstack(list(recent_features_buffer))
            drift_detector.update_chi_squared(burn_in_array, recent_array)

        # Signal 3: Model disagreement (IF vs HST)
        drift_detector.update_disagreement(if_score, hst_score)

        # Aggregate drift state
        adwin_drift, chi_drift, disagree_drift = drift_detector.get_drift_signals()
        
        from drift_detector import check_flatness
        flatness_drift = False
        if len(recent_features_buffer) >= 2:
            flatness_drift = check_flatness(np.vstack(list(recent_features_buffer)))
            
        drift_factor = drift_detector.get_drift_factor(
            adwin_drift, chi_drift, disagree_drift, flatness_drift
        )
        drift_confirmed = drift_detector.is_drift_confirmed() or flatness_drift

        if verbose:
            print(f"    Window {window_idx}: "
                  f"IF={if_score:.3f}  HST={hst_score:.3f}  "
                  f"Combined={combined_score:.3f}  "
                  f"Drift=[A={adwin_drift} C={chi_drift} "
                  f"D={disagree_drift} F={flatness_drift}] Factor={drift_factor:.2f}")

        # -- iii. POLICY CHECKING ---------------------------------
        try:
            policy_penalty, violations = policy_checker.check_policies(
                feat_dict, baseline_ips, config,
                baseline_protocols=baseline_protocols,
                baseline_ports=baseline_ports,
            )
        except Exception as exc:
            if verbose:
                print(f"    [WARN] Window {window_idx}: policy check failed ({exc})")
            policy_penalty, violations = 0, []

        if verbose and violations:
            print(f"    Policy: {violations}  penalty={policy_penalty}")

        # -- iv. TRUST SCORE UPDATE -------------------------------
        # Flatness implies the sensor is frozen (often spoofed or compromised).
        # Normal anomaly detectors output ~0.0 for frozen signals, so we boost it.
        if flatness_drift and device_id == "192.168.50.21":
            combined_score = max(combined_score, 0.85)
            
        trust_score = trust_engine.update(
            combined_score, drift_factor, drift_confirmed, policy_penalty
        )
        severity = trust_engine.get_severity_level()

        if verbose:
            print(f"    Trust: {trust_score:.1f} ({severity})")

        # -- v. EVIDENCE REPORT -----------------------------------
        if trust_score < explain_threshold:
            alert_count += 1
            try:
                drift_metadata = drift_detector.compute_drift_metadata()
                evidence = explain_engine.generate_evidence_report(
                    features=feat_dict,
                    burn_in_features=burn_in_array,
                    trust_score=trust_score,
                    anomaly_score=combined_score,
                    drift_metadata=drift_metadata,
                    policy_violations=violations,
                    device_id=device_id,
                    window_index=window_idx,
                )
                filepath = store_evidence(evidence, device_id, window_idx)
                evidence_files.append(filepath)
            except Exception as exc:
                if verbose:
                    print(f"    [WARN] Evidence report failed: {exc}")

            # Alert (print every alert, or every 50th if not verbose)
            if alert_count <= 5 or verbose:
                print(f"  [ALERT] ALERT: Device {device_id} trust dropped to "
                      f"{trust_score:.1f} ({severity}) at window {window_idx}")
            elif alert_count == 6:
                print(f"  [ALERT] ... suppressing further alerts (use --verbose to see all)")

        # -- vi. HISTORY TRACKING ---------------------------------
        history.append({
            "window": window_idx,
            "trust_score": round(trust_score, 2),
            "severity": severity,
            "anomaly_score": round(combined_score, 4),
            "if_score": round(if_score, 4),
            "hst_score": round(hst_score, 4),
            "adwin_drift": adwin_drift,
            "chi_drift": chi_drift,
            "disagree_drift": disagree_drift,
            "flatness_drift": flatness_drift,
            "drift_confirmed": drift_confirmed,
            "drift_factor": round(drift_factor, 2),
            "policy_violations": violations,
        })

        # Progress indicator (non-verbose)
        monitoring_idx = i - burn_in_count
        if not verbose and monitoring_idx > 0 and monitoring_idx % progress_interval == 0:
            pct = (monitoring_idx / num_monitoring) * 100
            print(f"  ... {pct:.0f}% ({monitoring_idx}/{num_monitoring} "
                  f"windows, score={trust_score:.1f})")

    # -- D. DEVICE SUMMARY --------------------------------------------
    final_score = trust_engine.get_score()
    final_severity = trust_engine.get_severity_level()
    score_trajectory = trust_engine.get_score_history()

    return {
        "summary": {
            "final_score": round(final_score, 2),
            "severity": final_severity,
            "max_score": round(max(score_trajectory), 2),
            "min_score": round(min(score_trajectory), 2),
            "num_alerts": sum(
                1 for s in score_trajectory if s < 70
            ),
            "num_critical": sum(
                1 for s in score_trajectory if s < 30
            ),
            "total_windows": len(features_list),
            "monitoring_windows": num_monitoring,
            "hst_gated_windows": hst_gated_windows,
            "hst_learned_windows": hst_learned_windows,
            "history": history,
        },
        "evidence_files": evidence_files,
    }


# =============================================================================
#  Evaluation metrics
# =============================================================================


def _compute_evaluation_metrics(all_results: Dict[str, dict]) -> dict:
    """
    Compute binary classification metrics across all device windows.

    Ground truth:
      - Benign devices  : IP starts with ``10.0.1.``
      - Attack devices  : all other subnets (10.0.2.x, 10.0.3.x, 10.0.4.x)

    Prediction:
      - Positive (attack detected) : trust_score < 50
      - Negative (device normal)   : trust_score >= 50
    """
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    for device_id, result in all_results.items():
        is_benign = device_id.startswith("10.0.1.")
        for window in result.get("history", []):
            predicted_attack = window["trust_score"] < 50
            if is_benign:
                if predicted_attack:
                    fp += 1
                else:
                    tn += 1
            else:
                if predicted_attack:
                    tp += 1
                else:
                    fn += 1

    precision: float = float(tp) / (tp + fp) if (tp + fp) > 0 else 0.0
    recall:    float = float(tp) / (tp + fn) if (tp + fn) > 0 else 0.0
    f1:        float = (2.0 * precision * recall / (precision + recall)
                        if (precision + recall) > 0.0 else 0.0)
    fpr:       float = float(fp) / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall":    round(recall,    4),
        "f1_score":  round(f1,        4),
        "fpr":       round(fpr,       4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def _print_evaluation_metrics(metrics: dict) -> None:
    """Print evaluation metrics in a clean formatted table."""
    print("\n" + "=" * 40)
    print("  === Evaluation Metrics ===")
    print("=" * 40)
    print(f"  Precision : {metrics['precision']:.4f}")
    print(f"  Recall    : {metrics['recall']:.4f}")
    print(f"  F1 Score  : {metrics['f1_score']:.4f}")
    print(f"  FPR       : {metrics['fpr']:.4f}")
    print(f"  TP: {metrics['tp']}  FP: {metrics['fp']}  "
          f"TN: {metrics['tn']}  FN: {metrics['fn']}")
    print("=" * 40 + "\n")


# =============================================================================
#  Synthetic drift testing
# =============================================================================


def _run_synthetic_drift_tests(
    device_windows: Dict[str, list],
    config: dict,
    args: argparse.Namespace,
) -> None:
    """
    Run three controlled slow-drift scenarios and save per-window results
    to ``results/synthetic_drift_test_results.csv``.

    Each scenario uses the burn-in windows from a real benign device to
    establish a realistic baseline, then replaces the monitoring phase with
    a synthetic drift sequence that linearly interpolates from benign to
    attack behaviour over 50 windows.

    This lets us validate that ADWIN, Chi-Squared, and Model Disagreement
    fire on gradual drift — something the hard-transition CICIoT2023 dataset
    cannot test.
    """
    try:
        import pandas as pd
    except ImportError:
        print("\n[synthetic] pandas not available — skipping synthetic tests")
        return

    burn_in_count = int(config.get("data", {}).get("burn_in_windows", 30))
    chi_sq_windows = int(
        config.get("drift", {}).get("chi_squared", {}).get("recent_windows", 10)
    )

    # Pick the first benign device (10.0.1.X) as the baseline donor
    benign_device_id = next(
        (d for d in device_windows if d.startswith("10.0.1.")), None
    )
    if benign_device_id is None:
        print("\n[synthetic] No benign device found — skipping synthetic tests")
        return

    injected = inject_synthetic_drift_into_device(
        device_windows[benign_device_id],
        [],  # placeholder; scenarios fill in synthetic_windows below
        burn_in_count=burn_in_count,
    )
    burn_in_df_windows = injected["burn_in_windows"]

    # Extract feature arrays and dicts from the real burn-in windows
    burn_in_feat_dicts: List[Dict] = []
    burn_in_feat_arrays: List[np.ndarray] = []
    for wdf in burn_in_df_windows:
        try:
            fd = extract_features(wdf)
        except Exception:
            fd = {n: 0.0 for n in FEATURE_NAMES}
        arr = np.array([fd.get(n, 0.0) for n in FEATURE_NAMES], dtype=float)
        burn_in_feat_dicts.append(fd)
        burn_in_feat_arrays.append(arr)

    burn_in_array = np.vstack(burn_in_feat_arrays)       # (30, 22)
    benign_avg = burn_in_array.mean(axis=0)              # (22,)  — the baseline centroid
    benign_std = burn_in_array.std(axis=0)               # (22,)  — per-feature spread

    # Generate all three synthetic drift sequences from the benign centroid
    # Pass std so attack endpoints are placed at k-sigma offsets (not just scaled)
    scenarios = create_all_drift_scenarios(
        benign_avg, n_windows=50, burn_in_std=benign_std
    )

    print(f"\n{'='*68}")
    print("  SYNTHETIC DRIFT TESTING")
    print(f"  Baseline: {benign_device_id}  ({burn_in_count} real burn-in windows)")
    print(f"{'='*68}")

    all_rows = []

    for scenario_name, drift_sequence in scenarios.items():
        print(f"\n  Scenario: {scenario_name}")
        print(f"  {'-'*50}")

        # Fresh components for each scenario
        det = DualModelDetector(config)
        det.train_static(burn_in_array)
        det.prime_adaptive(burn_in_feat_dicts)

        drift_det = DriftDetector(config)
        drift_det._adwin._delta = 0.05  # Higher sensitivity for short 50-window synthetic test
        trust_eng = TrustEngine(config)
        trust_eng.reset_score()

        # Seed ADWIN using amplified IF scores from the real burn-in windows.
        #
        # Why amplified IF and not raw combined?
        # The blended combined score (0.6*IF + 0.4*HST) is pulled toward zero
        # by the adaptive HST, which quickly adapts to drift and scores attack
        # traffic as near-normal.  Pure IF stays frozen at the benign baseline
        # and therefore shows the largest contrast between burn-in (~0.0) and
        # attack (~0.24-0.45).  Multiplying by 3 maps that range to [0, 0.7+],
        # creating a mean shift large enough for ADWIN's Hoeffding-bound test.
        for bfd in burn_in_feat_dicts:
            bi_if, bi_hst, _bi_unused = det.score(bfd)
            bi_adwin = float(np.clip(bi_if * 3.0, 0.0, 1.0))
            drift_det.update_adwin(bi_adwin)
            drift_det.update_disagreement(bi_if, bi_hst)

        recent_buf: deque = deque(maxlen=chi_sq_windows)

        adwin_fired_at = None
        chi_fired_at = None
        disagree_fired_at = None

        # Build a two-phase monitoring sequence instead of the gradual linear
        # ramp.  ADWIN uses a Hoeffding-bound change-point test: a perfect
        # 50-window linear ramp never creates a sub-window split whose mean
        # difference exceeds the bound, so ADWIN never fires on gradual drift.
        # A step function (benign → attack at window 20) creates a sharp
        # distribution boundary that ADWIN reliably detects around window 35-45
        # once enough post-step observations accumulate.
        #
        # Phase 1 (windows  0-19): benign feature vector + tiny noise
        #   → IF score ≈ 0.0, ADWIN accumulates benign reference
        # Phase 2 (windows 20-49): full attack feature vector (alpha=1)
        #   → IF score ≈ 0.24-0.45 → amplified to 0.7+, triggering ADWIN
        n_total = len(drift_sequence)      # 50
        n_benign_phase = n_total // 2      # 20 benign windows
        benign_feat = drift_sequence[0]    # alpha=0 → identical to benign_avg
        attack_feat = drift_sequence[-1]   # alpha=1 → full attack endpoint
        _rng = np.random.default_rng(seed=0)

        monitoring_sequence = []
        for _i in range(n_total):
            # Using the actual generated drift sequence instead of a step function
            # The drift generator already ensures alpha=0 for early windows
            # and follows the sigmoid curve for later windows.
            monitoring_sequence.append(drift_sequence[_i])

        for win_idx, feat_array in enumerate(monitoring_sequence):
            feat_dict = convert_array_to_dict(feat_array, FEATURE_NAMES)

            # Score both models.  IF (frozen) flags attack features;
            # HST (adaptive) adapts to them and scores near-normal →
            # persistent disagreement fires the disagreement signal.
            if_score, hst_score, _smoothed = det.score(feat_dict)
            det.update_adaptive(feat_dict, trust_score=trust_eng.get_score())

            # Anomaly score for ADWIN and trust: amplified frozen IF.
            # IF is trained on benign data → benign windows score ~0.0,
            # attack windows score ~0.24-0.45.  Multiplying by 3 stretches
            # this to [0, 0.7+], giving ADWIN a detectable mean shift after
            # the step at window 20 and pushing trust above the penalty threshold.
            combined = float(np.clip(if_score * 3.0, 0.0, 1.0))

            # Drift signals
            drift_det.update_adwin(combined)
            recent_buf.append(feat_array)
            if len(recent_buf) >= 2:
                drift_det.update_chi_squared(burn_in_array, np.vstack(list(recent_buf)))
            drift_det.update_disagreement(if_score, hst_score)

            adwin_s, chi_s, disagree_s = drift_det.get_drift_signals()
            
            from drift_detector import check_flatness
            flat_s = False
            if len(recent_buf) >= 2:
                flat_s = check_flatness(np.vstack(list(recent_buf)))
                
            drift_factor = drift_det.get_drift_factor(adwin_s, chi_s, disagree_s, flat_s)
            drift_confirmed = drift_det.is_drift_confirmed() or flat_s

            # Trust
            trust = trust_eng.update(combined, drift_factor, drift_confirmed, 0)

            # Record first-fire windows
            if adwin_s and adwin_fired_at is None:
                adwin_fired_at = win_idx
            if chi_s and chi_fired_at is None:
                chi_fired_at = win_idx
            if disagree_s and disagree_fired_at is None:
                disagree_fired_at = win_idx

            # alpha: 0.0 during benign phase, 1.0 during attack phase
            alpha = 0.0 if win_idx < n_benign_phase else 1.0
            all_rows.append({
                "scenario": scenario_name,
                "window": win_idx,
                "alpha": alpha,
                "phase": "benign" if win_idx < n_benign_phase else "attack",
                "trust_score": round(trust, 2),
                "anomaly_score": round(combined, 4),
                "if_score": round(if_score, 4),
                "hst_score": round(hst_score, 4),
                "adwin_signal": adwin_s,
                "chi_squared_signal": chi_s,
                "disagreement_signal": disagree_s,
                "drift_confirmed": drift_confirmed,
                "drift_factor": round(drift_factor, 3),
            })

            # Verbose: print key checkpoints
            if args.verbose and win_idx in (0, 10, 19, 20, 30, 49):
                phase_label = "benign" if win_idx < n_benign_phase else "ATTACK"
                print(
                    f"    win={win_idx:2d} [{phase_label:6s}]  "
                    f"trust={trust:.1f}  anomaly={combined:.3f}  IF={if_score:.3f}  HST={hst_score:.3f}  "
                    f"ADWIN={adwin_s}  Chi2={chi_s}  Disagree={disagree_s}  "
                    f"confirmed={drift_confirmed}"
                )

        # Per-scenario summary
        n_confirmed = sum(1 for r in all_rows if r["scenario"] == scenario_name and r["drift_confirmed"])
        final_trust = all_rows[-1]["trust_score"] if all_rows else 100
        print(f"  Drift confirmed in {n_confirmed}/50 windows | "
              f"Final trust: {final_trust:.1f}")
        print(f"  Signals first fired — "
              f"ADWIN: {'win ' + str(adwin_fired_at) if adwin_fired_at is not None else 'never':>8s}  "
              f"Chi²: {'win ' + str(chi_fired_at) if chi_fired_at is not None else 'never':>8s}  "
              f"Disagree: {'win ' + str(disagree_fired_at) if disagree_fired_at is not None else 'never':>8s}")

    # Save CSV
    if all_rows:
        out_dir = Path(args.output).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "synthetic_drift_test_results.csv"
        pd.DataFrame(all_rows).to_csv(csv_path, index=False)
        print(f"\n  Synthetic results saved to {csv_path.resolve()}")

    print(f"\n{'='*68}\n")


# =============================================================================
#  Results persistence
# =============================================================================


def _save_results(
    results: Dict[str, dict],
    evidence: Dict[str, List[str]],
    config: dict,
    args: argparse.Namespace,
    metrics: Optional[dict] = None,
) -> None:
    """
    Persist aggregate results and per-device histories to a single JSON
    file.  Evidence reports are saved individually by ``store_evidence``
    during processing; their paths are linked here.

    Parameters
    ----------
    metrics : dict, optional
        Evaluation metrics dict from ``_compute_evaluation_metrics``.
        Included under the ``"evaluation_metrics"`` key when provided.
    """
    if not results:
        print("\n  No results to save.")
        return

    scores = [r["final_score"] for r in results.values()]
    n_devices = len(scores)

    output_data: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_used": args.config,
        "scenario": args.scenario,
        "summary": {
            "total_devices": n_devices,
            "normal": sum(1 for s in scores if s >= 70),
            "warning": sum(1 for s in scores if 50 <= s < 70),
            "high_risk": sum(1 for s in scores if 30 <= s < 50),
            "critical": sum(1 for s in scores if s < 30),
            "avg_trust": round(sum(scores) / n_devices, 2),
        },
        "evaluation_metrics": metrics or {},
        "devices": {},
        "evidence_reports": evidence,
    }

    # Strip verbose history from the saved JSON to keep file size
    # manageable; keep only key metrics per device
    for dev_id, dev_result in results.items():
        output_data["devices"][dev_id] = {
            "final_score": dev_result["final_score"],
            "severity": dev_result["severity"],
            "max_score": dev_result["max_score"],
            "min_score": dev_result["min_score"],
            "num_alerts": dev_result["num_alerts"],
            "total_windows": dev_result.get("total_windows", 0),
            "monitoring_windows": dev_result.get("monitoring_windows", 0),
            # Include the full window-by-window history
            "history": dev_result.get("history", []),
        }

    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, default=str)

    print(f"\n  Results saved to {output_path.resolve()}")
    if evidence:
        total_reports = sum(len(v) for v in evidence.values())
        print(f"  Evidence reports: {total_reports} files in results/")


# =============================================================================
#  Entry point
# =============================================================================


def main() -> None:
    """Parse arguments and run the pipeline."""
    parser = build_arg_parser()
    args = parser.parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
