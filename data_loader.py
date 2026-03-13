"""
data_loader.py - IoT Trust & Drift Analytics System

Loads the CICIoT2023 preprocessed dataset from CSV files and constructs
a realistic device simulation where:
  - 20 synthetic IoT devices are created
  - ALL devices receive benign traffic during the burn-in period
  - After burn-in, some devices transition to attack traffic, simulating
    real-world compromise scenarios

Device layout (default 20 devices):
  - 5 "Benign-only" control devices   -> benign traffic throughout
  - 5 "DDoS" devices                  -> benign burn-in, then DDoS-SYN_Flood
  - 5 "Mirai" devices                 -> benign burn-in, then Mirai-udpplain
  - 5 "Recon" devices                 -> benign burn-in, then Recon-PortScan

Records are taken as consecutive blocks (not random samples) to preserve
natural statistical correlations within the data.  This avoids artificial
variance that would cause the anomaly detector to false-fire on benign data.
"""

import os
import pandas as pd
from typing import Dict, List, Optional


# ── Configuration constants ──────────────────────────────────────────────
DEVICES_PER_CATEGORY = 5       # Devices per attack type (and for control)
BURN_IN_WINDOWS = 30           # Windows of benign traffic per device
MONITORING_WINDOWS = 20        # Windows of attack (or continued benign)
FLOWS_PER_WINDOW = 500         # Flow records per window
WINDOW_SIZE_SECONDS = 60       # Kept for API compatibility

# Label detection
_LABEL_CANDIDATES = ["label", "Label", "LABEL"]
_BENIGN_LABELS = {"Benign", "benign", "BENIGN", "Normal", "normal"}


# ── helpers ──────────────────────────────────────────────────────────────


def _find_label_column(columns: pd.Index) -> Optional[str]:
    """Return the label column name if found."""
    for name in _LABEL_CANDIDATES:
        if name in columns:
            return name
    return None


def _is_benign_file(df: pd.DataFrame) -> bool:
    """Check if a DataFrame contains only benign traffic."""
    label_col = _find_label_column(df.columns)
    if label_col is None:
        return False
    unique_labels = set(df[label_col].dropna().unique())
    return unique_labels.issubset(_BENIGN_LABELS)


def _load_csvs_by_type(data_dir: str) -> tuple:
    """
    Load all CSVs and separate into benign and attack DataFrames.

    Returns
    -------
    (benign_df, attack_dict)
        attack_dict maps attack_name -> DataFrame.
    """
    csv_files = sorted(
        f for f in os.listdir(data_dir) if f.lower().endswith(".csv")
    )
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    benign_frames: list = []
    attack_dfs: Dict[str, pd.DataFrame] = {}

    for fname in csv_files:
        path = os.path.join(data_dir, fname)
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"[data_loader] WARNING: skipping {fname} ({exc})")
            continue

        name = os.path.splitext(fname)[0]

        if _is_benign_file(df):
            benign_frames.append(df)
            print(f"[data_loader] Loaded BENIGN: {fname} ({len(df):,} records)")
        else:
            attack_dfs[name] = df
            print(f"[data_loader] Loaded ATTACK: {fname} ({len(df):,} records)")

    if not benign_frames:
        raise ValueError(
            "No Benign CSV found. Need at least one CSV with all-Benign labels."
        )

    benign_df = pd.concat(benign_frames, ignore_index=True)
    print(f"[data_loader] Benign pool: {len(benign_df):,} records")
    print(f"[data_loader] Attack types: {list(attack_dfs.keys())}")
    return benign_df, attack_dfs


def _chunk_into_windows(
    flows_df: pd.DataFrame,
    flows_per_window: int,
    min_flows: int = 5,
) -> List[pd.DataFrame]:
    """Split a DataFrame into fixed-size window chunks."""
    windows: List[pd.DataFrame] = []
    n_total = len(flows_df)
    for start in range(0, n_total, flows_per_window):
        end = min(start + flows_per_window, n_total)
        chunk = flows_df.iloc[start:end].reset_index(drop=True)
        if len(chunk) >= min_flows:
            windows.append(chunk)
    return windows


# ── public API ───────────────────────────────────────────────────────────


def load_dataset(
    data_dir: Optional[str] = None,
    window_size: float = WINDOW_SIZE_SECONDS,
) -> Dict[str, List[pd.DataFrame]]:
    """
    Load the CICIoT2023 dataset and return windowed per-device DataFrames.

    Creates a realistic simulation where every device starts with benign
    traffic (burn-in), and attack devices transition to malicious traffic
    afterward.  Records are taken as consecutive blocks to preserve
    natural statistical properties.

    Parameters
    ----------
    data_dir : str or None
        Directory containing CICIoT2023 CSV files.
        Defaults to the directory where this script is located.
    window_size : float
        Kept for API compatibility (windows are sized by flow count).

    Returns
    -------
    dict[str, list[pd.DataFrame]]
        Mapping from device IP to a list of window DataFrames.
    """
    if data_dir is None:
        data_dir = os.path.dirname(os.path.abspath(__file__))

    benign_df, attack_dfs = _load_csvs_by_type(data_dir)

    # Shuffle benign data once so every consecutive block is a
    # representative mix of all benign traffic types (web, DNS, IRC, etc.).
    # This ensures burn-in captures the full service profile, preventing
    # false positives from services that appear later.
    benign_df = benign_df.sample(frac=1, random_state=42).reset_index(drop=True)

    result: Dict[str, List[pd.DataFrame]] = {}
    total_windows = BURN_IN_WINDOWS + MONITORING_WINDOWS
    flows_per_device = total_windows * FLOWS_PER_WINDOW

    # ── 1. Create benign control devices ─────────────────────────────
    # Each device gets a consecutive block from the shuffled benign pool.
    print(f"\n[data_loader] Creating {DEVICES_PER_CATEGORY} benign control devices...")
    benign_offset = 0
    for d in range(DEVICES_PER_CATEGORY):
        device_ip = f"10.0.1.{d + 1}"
        end = benign_offset + flows_per_device
        if end <= len(benign_df):
            device_flows = benign_df.iloc[benign_offset:end].reset_index(drop=True)
        else:
            # Wrap around if we run out of benign data
            part1 = benign_df.iloc[benign_offset:]
            remaining = flows_per_device - len(part1)
            part2 = benign_df.iloc[:remaining]
            device_flows = pd.concat([part1, part2], ignore_index=True)
        benign_offset = end % len(benign_df)

        windows = _chunk_into_windows(device_flows, FLOWS_PER_WINDOW)
        result[device_ip] = windows
        print(f"  {device_ip}: {len(windows)} windows (all benign)")

    # ── 2. Create attack devices (benign burn-in -> attack) ──────────
    # Burn-in uses consecutive benign blocks; monitoring uses consecutive
    # attack blocks.
    attack_types = sorted(attack_dfs.keys())
    n_benign_burn_in = BURN_IN_WINDOWS * FLOWS_PER_WINDOW

    for atk_idx, attack_name in enumerate(attack_types):
        subnet = atk_idx + 2  # subnets 2, 3, 4, ...
        attack_df = attack_dfs[attack_name]
        attack_offset = 0
        n_attack_per_device = MONITORING_WINDOWS * FLOWS_PER_WINDOW

        print(f"\n[data_loader] Creating {DEVICES_PER_CATEGORY} "
              f"{attack_name} devices...")

        for d in range(DEVICES_PER_CATEGORY):
            device_ip = f"10.0.{subnet}.{d + 1}"

            # Benign burn-in: consecutive block from benign pool
            b_end = benign_offset + n_benign_burn_in
            if b_end <= len(benign_df):
                benign_chunk = benign_df.iloc[benign_offset:b_end].reset_index(drop=True)
            else:
                part1 = benign_df.iloc[benign_offset:]
                remaining = n_benign_burn_in - len(part1)
                part2 = benign_df.iloc[:remaining]
                benign_chunk = pd.concat([part1, part2], ignore_index=True)
            benign_offset = b_end % len(benign_df)

            # Attack monitoring: consecutive block from attack pool
            a_end = attack_offset + n_attack_per_device
            if a_end <= len(attack_df):
                attack_chunk = attack_df.iloc[attack_offset:a_end].reset_index(drop=True)
            else:
                part1 = attack_df.iloc[attack_offset:]
                remaining = n_attack_per_device - len(part1)
                part2 = attack_df.iloc[:remaining]
                attack_chunk = pd.concat([part1, part2], ignore_index=True)
            attack_offset = a_end % len(attack_df)

            # Concatenate: benign first, then attack
            device_flows = pd.concat(
                [benign_chunk, attack_chunk], ignore_index=True,
            )
            windows = _chunk_into_windows(device_flows, FLOWS_PER_WINDOW)
            result[device_ip] = windows
            print(f"  {device_ip}: {len(windows)} windows "
                  f"(30 benign + 20 {attack_name})")

    total_win = sum(len(w) for w in result.values())
    print(f"\n[data_loader] Result: {len(result)} devices, "
          f"{total_win} total windows")
    return result


# ── Synthetic drift injection ────────────────────────────────────────────


def inject_synthetic_drift_into_device(
    real_device_windows: List[pd.DataFrame],
    synthetic_drift_sequence,
    burn_in_count: int = BURN_IN_WINDOWS,
) -> dict:
    """
    Combine real burn-in windows with a synthetic drift sequence.

    Returns a dict with separate burn-in and monitoring parts so the
    synthetic testing loop in main.py can process them without needing
    to run extract_features on the synthetic arrays (they are already
    feature vectors, not raw DataFrames).

    Parameters
    ----------
    real_device_windows : list of pd.DataFrame
        Full window list for a real device (burn-in + original monitoring).
        Only the first *burn_in_count* windows are used.
    synthetic_drift_sequence : list of np.ndarray
        Feature arrays produced by ``synthetic_drift_generator``.
        Each array has shape ``(22,)``.
    burn_in_count : int
        Number of real burn-in windows to keep (default 30).

    Returns
    -------
    dict with keys:
        ``burn_in_windows``   — list of DataFrames (first 30 real windows)
        ``synthetic_windows`` — list of np.ndarray  (50 synthetic drift windows)
    """
    return {
        "burn_in_windows": real_device_windows[:burn_in_count],
        "synthetic_windows": list(synthetic_drift_sequence),
    }


# ── quick smoke-test when run directly ───────────────────────────────────

if __name__ == "__main__":
    data = load_dataset()
    for ip, windows in list(data.items())[:5]:
        print(f"\nDevice {ip}: {len(windows)} windows")
        for i, w in enumerate(windows[:2]):
            print(f"  Window {i}: {w.shape[0]} records, {w.shape[1]} features")
            if "label" in w.columns:
                print(f"    Labels: {w['label'].value_counts().to_dict()}")
