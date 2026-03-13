"""
simulate_live.py — Replay results.json to the live server window-by-window.

Iterates over devices (optionally filtered by --device), sends 30 synthetic
burn-in windows so the server can build its baseline, then replays the
recorded monitoring history from results.json with a 1-second delay between
windows.

Usage
-----
    python simulate_live.py                        # all devices
    python simulate_live.py --device 10.0.2.1      # focused demo

NOTE: results.json stores only monitoring-phase data (windows after burn-in).
Feature values are not persisted in results.json, so /ingest payloads during
the replay phase are synthesised from available fields (trust_score,
anomaly_score) to produce realistic variability in bytes/destinations.
"""

import argparse
import json
import time
from pathlib import Path

import requests

SERVER_URL = "http://localhost:8000"
BURN_IN_WINDOWS = 30


def _send(payload: dict) -> dict:
    resp = requests.post(f"{SERVER_URL}/ingest", json=payload, timeout=5)
    resp.raise_for_status()
    return resp.json()


def _burn_in(device_id: str) -> None:
    """Send BURN_IN_WINDOWS synthetic baseline windows for device_id."""
    print(f"[{device_id}] Sending {BURN_IN_WINDOWS} burn-in windows...")
    for i in range(1, BURN_IN_WINDOWS + 1):
        payload = {
            "device_id":   device_id,
            "bytes_sent":  1240.0,
            "packets":     45.0,
            "dst_ips":     ["192.168.1.1"],
            "request_rate": 2.3,
            "mode":        0,
        }
        try:
            data = _send(payload)
            win = data.get("window", i)
            print(f"[{device_id}] window {i:3d} | burn-in ({win}/{BURN_IN_WINDOWS})")
        except requests.exceptions.ConnectionError:
            print(
                f"[ERROR] Cannot reach {SERVER_URL}. "
                "Is `uvicorn server:app --reload` running?"
            )
            raise
        except Exception as e:
            print(f"[{device_id}] window {i:3d} | error: {e}")
        time.sleep(1)


def _replay(device_id: str, history: list) -> None:
    """Replay monitoring windows from results.json history."""
    print(f"[{device_id}] Replaying {len(history)} monitoring windows...")
    for idx, window in enumerate(history, start=1):
        trust_score   = window.get("trust_score", 100.0)
        anomaly_score = window.get("anomaly_score", 0.0)

        # results.json does not persist raw feature values, so we derive
        # /ingest payload fields from the available recorded metrics.
        #   bytes_sent  = total_bytes proxy (scales with anomaly score)
        #   packets     = total_packets proxy (fixed)
        #   dst_ips     = list of length ≈ unique_dst_ips (scales with anomaly)
        #   request_rate = packets_per_sec proxy
        #   mode        = 0 if trust_score > 50 else 1
        n_ips = max(1, int(anomaly_score * 10))
        dst_ips = [f"10.{(j // 256) % 256}.{j % 256}.1" for j in range(n_ips)]

        payload = {
            "device_id":   device_id,
            "bytes_sent":  max(1.0, anomaly_score * 80_000 + 1_000),
            "packets":     45.0,
            "dst_ips":     dst_ips,
            "request_rate": 2.3 + anomaly_score * 5.0,
            "mode":        0 if trust_score > 50 else 1,
        }

        try:
            data = _send(payload)
            if data.get("status") == "burn_in":
                print(f"[{device_id}] window {idx:3d} | still in burn-in")
            else:
                live_trust = data.get("trust_score", trust_score)
                severity   = data.get("severity", "UNKNOWN")
                print(
                    f"[{device_id}] window {idx:3d} "
                    f"| trust: {live_trust:5.1f} | severity: {severity}"
                )
        except requests.exceptions.ConnectionError:
            print(
                f"[ERROR] Cannot reach {SERVER_URL}. "
                "Is `uvicorn server:app --reload` running?"
            )
            raise
        except Exception as e:
            print(f"[{device_id}] window {idx:3d} | error: {e}")

        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay results.json to the live server window-by-window."
    )
    parser.add_argument(
        "--device", type=str, default=None,
        help="Filter to a single device_id for focused demos.",
    )
    args = parser.parse_args()

    results_path = Path("results.json")
    if not results_path.exists():
        print("[ERROR] results.json not found. Run `python main.py` first.")
        return

    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)

    all_devices: dict = results.get("devices", {})

    if args.device:
        if args.device not in all_devices:
            print(f"[ERROR] Device '{args.device}' not found in results.json")
            print(f"        Available: {', '.join(sorted(all_devices.keys()))}")
            return
        all_devices = {args.device: all_devices[args.device]}

    for device_id, device_data in all_devices.items():
        history = device_data.get("history", [])
        try:
            _burn_in(device_id)
            _replay(device_id, history)
        except requests.exceptions.ConnectionError:
            return
        print()


if __name__ == "__main__":
    main()
