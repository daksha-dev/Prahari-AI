from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.engine.explainability import synthesize_evidence_explanation
from app.engine.feature_engineer import FEATURE_NAMES, mapping_from_vector
from app.simulator.device_simulator import BASE_BY_TYPE
from app.store.memory_store import store

ToolFunc = Callable[..., Awaitable[Any]]


class ToolExecutionError(RuntimeError):
    pass


async def list_flagged_devices(threshold: int = 70, limit: int = 10) -> list[dict[str, Any]]:
    devices = await store.list_devices()
    flagged = [d for d in devices if d["current_trust"] < threshold]
    return sorted(flagged, key=lambda d: d["current_trust"])[:limit]


async def get_device_trust(device_id: str) -> dict[str, Any]:
    device = await store.get_device(device_id)
    if not device:
        raise ToolExecutionError(f"Device {device_id} not found.")
    evidence = await store.read_evidence_card(device_id) or {}
    devices = await store.list_devices()
    meta = _device_metadata(device["device"])
    latest_features = _latest_feature_mapping(device_id)
    latest_z_scores = _latest_z_scores(device)
    return {
        "device": meta,
        "current_trust": device["current_trust"],
        "severity": device["severity"],
        "drift_confirmed": bool(device["device"].get("drift_confirmed", False)),
        "trust_history": _trust_history(device, evidence),
        "drift_status_history": _drift_status_history(device, evidence),
        "baseline_summary": _baseline_summary(device),
        "current_window_features": latest_features,
        "z_scores": latest_z_scores,
        "time_since_last_alert": _seconds_since(device["device"].get("last_alert_time")),
        "peer_comparison": _peer_comparison(meta, device["current_trust"], devices),
        "narration": device.get("narration"),
    }


async def explain_drift(device_id: str) -> dict[str, Any]:
    evidence = await store.read_evidence_card(device_id)
    if not evidence:
        raise ToolExecutionError(f"No evidence available for {device_id}.")
    result = dict(evidence)
    device = await get_device_trust(device_id)
    attack_pattern, confidence, matched_signals = _attack_pattern(device)
    started_window = _drift_started_window(device)
    result["drift_started_window"] = started_window
    result["drift_duration_seconds"] = _drift_duration_seconds(device, started_window)
    result["similar_past_incidents"] = await _similar_past_incidents(device_id)
    result["attack_pattern_match"] = attack_pattern
    result["confidence"] = confidence
    result["corroborating_signals"] = matched_signals
    result["human_explanation"] = _human_explanation(device, result)
    result["explanation"] = synthesize_evidence_explanation(result)
    return result


async def get_network_summary() -> dict[str, Any]:
    return await store.network_summary()


async def system_remediation(device_id: str, platform: str = "iptables") -> dict[str, Any]:
    device = await store.get_device(device_id)
    if not device:
        raise ToolExecutionError(f"Device {device_id} not found.")
    trust_context = await get_device_trust(device_id)
    ip = trust_context["device"].get("ip", device_id)
    evidence = await explain_drift(device_id) if await store.read_evidence_card(device_id) else {}
    platform = platform.lower()
    if platform == "powershell":
        block_script = (
            f"New-NetFirewallRule -DisplayName \"Block Prahari device {ip}\" "
            f"-Direction Outbound -RemoteAddress {ip} -Action Block\n"
            f"New-NetFirewallRule -DisplayName \"Block inbound Prahari device {ip}\" "
            f"-Direction Inbound -RemoteAddress {ip} -Action Block"
        )
    elif platform == "iptables":
        block_script = f"iptables -I INPUT -s {ip} -j DROP\niptables -I OUTPUT -d {ip} -j DROP"
    else:
        return {
            "block_script": "",
            "playbook": [],
            "explanation": "Unsupported platform. Use 'iptables' or 'powershell'.",
            "rationale": "No remediation was generated because the requested platform is unsupported.",
            "estimated_impact": "medium",
            "reversibility": "fully_reversible",
            "related_devices": [],
        }

    policy_count = len(evidence.get("policy_violations", []))
    playbook = [
        f"Disconnect {device['device'].get('name', device_id)} from the network or place it on a quarantine VLAN.",
        "Review router, DNS, and firewall logs for lateral movement or repeated blocked destinations.",
        "Factory reset or reflash firmware before reconnecting, then watch trust recovery for several clean windows.",
    ]
    if policy_count:
        playbook[1] = f"Review router, DNS, and firewall logs for the {policy_count} policy violation(s) seen in the evidence card."

    return {
        "block_script": block_script,
        "playbook": playbook,
        "explanation": f"This remediation blocks traffic for {ip} and gives the analyst a short containment and recovery checklist.",
        "rationale": _remediation_rationale(trust_context, evidence),
        "estimated_impact": _estimated_impact(trust_context["device"]["type"]),
        "reversibility": _reversibility(trust_context["device"]["type"]),
        "related_devices": await _related_devices(trust_context["device"]),
    }


async def get_recent_activity(minutes: int = 10) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, minutes) * 60
    alerts = [alert for alert in await store.alerts() if _timestamp(alert.get("timestamp_iso")) >= cutoff]
    timeline = []
    patterns = []
    for alert in sorted(alerts, key=lambda item: item.get("timestamp_iso", "")):
        evidence = await store.read_evidence_card(alert["device_id"]) or {}
        try:
            drift = await explain_drift(alert["device_id"])
            patterns.append(drift.get("attack_pattern_match", "unknown"))
        except ToolExecutionError:
            drift = {}
            patterns.append("unknown")
        changed = f"trust dropped to {alert.get('trust')} with {', '.join(evidence.get('drift_signals_fired', []) or ['no drift signal'])}"
        timeline.append(
            {
                "timestamp": alert.get("timestamp_iso"),
                "device_id": alert["device_id"],
                "severity": alert.get("severity"),
                "what_changed": changed,
                "attack_pattern_match": drift.get("attack_pattern_match", "unknown"),
            }
        )
    return {
        "minutes": minutes,
        "alert_timeline": timeline,
        "score_changes": await _score_changes(minutes),
        "dominant_attack_pattern": Counter(patterns).most_common(1)[0][0] if patterns else "unknown",
    }


async def compare_devices(device_ids: list[str]) -> dict[str, Any]:
    if not 2 <= len(device_ids) <= 5:
        raise ToolExecutionError("compare_devices requires 2 to 5 device IDs.")
    comparisons = []
    z_by_device = {}
    for device_id in device_ids:
        trust = await get_device_trust(device_id)
        drift = await explain_drift(device_id) if await store.read_evidence_card(device_id) else {}
        top_features = drift.get("top_deviating_features", [])[:3]
        comparisons.append(
            {
                "device_id": device_id,
                "name": trust["device"]["name"],
                "trust": trust["current_trust"],
                "severity": trust["severity"],
                "top_3_deviating_features": top_features,
                "drift_status": {
                    "drift_confirmed": trust["drift_confirmed"],
                    "latest_signals": trust["drift_status_history"][-1]["signals_fired"] if trust["drift_status_history"] else [],
                    "attack_pattern_match": drift.get("attack_pattern_match", "unknown"),
                },
            }
        )
        z_by_device[device_id] = trust["z_scores"]
    return {"devices": comparisons, "highlights": _comparison_highlights(z_by_device)}


def _device_metadata(device: dict[str, Any]) -> dict[str, Any]:
    name = device.get("name", device.get("device_id", "unknown"))
    return {
        "device_id": device.get("device_id", device.get("ip")),
        "name": name,
        "ip": device.get("ip", device.get("device_id")),
        "type": device.get("device_type", "unknown"),
        "device_type": device.get("device_type", "unknown"),
        "vendor": "generic",
        "location": _location_for(name, device.get("device_id", "")),
    }


def _location_for(name: str, device_id: str) -> str:
    text = f"{name} {device_id}".lower()
    if "kitchen" in text:
        return "Kitchen"
    if "bedroom" in text:
        return "Bedroom"
    if "living" in text or "tv" in text or "speaker" in text:
        return "Living Room"
    if "front" in text or "doorbell" in text:
        return "Front Door"
    if "back" in text:
        return "Back Door"
    if "office" in text or "esp32" in text:
        return "Office"
    if "thermostat" in text:
        return "Hallway"
    return "Utility Area"


def _trust_history(device: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = device.get("trust_history", [])[-30:]
    drifts = device.get("drift_status", [])[-30:]
    latest_window = int(evidence.get("window_id", len(rows)) or len(rows))
    first_window = max(1, latest_window - len(rows) + 1)
    latest_anomaly = float(evidence.get("smoothed_score", evidence.get("raw_anomaly_score", 0.0)) or 0.0)
    history = []
    for index, row in enumerate(rows):
        drift = drifts[index] if index < len(drifts) else {}
        history.append(
            {
                "window_id": first_window + index,
                "timestamp": row.get("timestamp"),
                "trust_score": row.get("trust"),
                "anomaly_score": latest_anomaly if index == len(rows) - 1 else None,
                "drift_factor": drift.get("factor", 1.0),
            }
        )
    return history


def _drift_status_history(device: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = device.get("drift_status", [])[-30:]
    latest_window = int(evidence.get("window_id", len(rows)) or len(rows))
    first_window = max(1, latest_window - len(rows) + 1)
    return [
        {
            "window_id": first_window + index,
            "confirmed": bool(row.get("confirmed", False)),
            "signals_fired": list(row.get("fired", [])),
            "adwin": bool(row.get("adwin", False)),
            "chi_squared": bool(row.get("chi_squared", False)),
            "model_disagreement": bool(row.get("model_disagreement", False)),
        }
        for index, row in enumerate(rows)
    ]


def _baseline_summary(device: dict[str, Any]) -> dict[str, dict[str, float]]:
    existing = device.get("baseline_summary") or {}
    if existing:
        return existing
    device_type = device["device"].get("device_type", "esp32")
    base = BASE_BY_TYPE.get(device_type, BASE_BY_TYPE["esp32"])
    important = ["bytes_per_sec", "packets_per_sec", "unique_dst_ips", "port_entropy", "flow_symmetry"]
    return {
        name: {
            "mean": round(float(base[FEATURE_NAMES.index(name)]), 4),
            "std": round(max(abs(float(base[FEATURE_NAMES.index(name)])) * 0.035, 0.02), 4),
        }
        for name in important
    }


def _latest_feature_mapping(device_id: str) -> dict[str, float]:
    rows = store.feature_histories.get(device_id)
    if not rows:
        return {name: 0.0 for name in FEATURE_NAMES}
    return {name: round(value, 4) for name, value in mapping_from_vector(rows[-1]).items()}


def _latest_z_scores(device: dict[str, Any]) -> dict[str, float]:
    rows = device.get("behavioral_heatmap", [])
    if not rows:
        return {name: 0.0 for name in FEATURE_NAMES}
    return {name: round(float(rows[-1][index]), 3) for index, name in enumerate(FEATURE_NAMES)}


def _seconds_since(timestamp_iso: str | None) -> int | None:
    if not timestamp_iso:
        return None
    return max(0, int(datetime.now(timezone.utc).timestamp() - _timestamp(timestamp_iso)))


def _timestamp(timestamp_iso: str | None) -> float:
    if not timestamp_iso:
        return 0.0
    return datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00")).timestamp()


def _peer_comparison(meta: dict[str, Any], trust: float, devices: list[dict[str, Any]]) -> dict[str, Any]:
    peers = [d for d in devices if d.get("device_type") == meta["type"] and d.get("device_id") != meta["device_id"]]
    peer_trusts = [float(d.get("current_trust", 0.0)) for d in peers]
    mean_peer_trust = round(sum(peer_trusts) / len(peer_trusts), 2) if peer_trusts else None
    return {
        "peer_type": meta["type"],
        "peer_count": len(peers),
        "mean_peer_trust": mean_peer_trust,
        "trust_delta_vs_peers": round(trust - mean_peer_trust, 2) if mean_peer_trust is not None else None,
    }


def _attack_pattern(device: dict[str, Any]) -> tuple[str, float, list[str]]:
    features = device["current_window_features"]
    z = device["z_scores"]
    signals: list[str] = []
    pattern = "unknown"
    if z.get("flow_symmetry", 0) < -2.5 and z.get("bytes_per_sec", 0) > 2.5:
        pattern = "data_exfiltration"
        signals = ["flow_symmetry highly negative", "bytes_per_sec elevated"]
    elif z.get("unique_dst_ips", 0) > 2.5 and z.get("port_entropy", 0) > 2.0:
        pattern = "lateral_scanning"
        signals = ["unique_dst_ips spiked", "port_entropy high"]
    elif z.get("packets_per_sec", 0) > 4.0 and z.get("burstiness", 0) > 3.0:
        pattern = "ddos_participation"
        signals = ["packets_per_sec extreme", "burstiness extreme"]
    elif z.get("new_dst_count", 0) > 2.0 and features.get("avg_payload_size", 0) < 160 and 0.2 <= features.get("mean_iat", 0) <= 6.0:
        pattern = "command_and_control"
        signals = ["periodic small flows", "new_dst_count elevated"]
    elif _coefficient_of_variation(list(features.values())) < 0.01:
        pattern = "frozen_sensor"
        signals = ["coefficient_of_variation near 0 across features"]
    drift_signals = device.get("drift_status_history", [])[-1].get("signals_fired", []) if device.get("drift_status_history") else []
    confidence = min(1.0, round((len(signals) + len(drift_signals)) / 4.0, 2))
    return pattern, confidence, signals + drift_signals


def _coefficient_of_variation(values: list[float]) -> float:
    mean = sum(values) / len(values) if values else 0.0
    if abs(mean) < 1e-9:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return (variance**0.5) / abs(mean)


def _drift_started_window(device: dict[str, Any]) -> int | None:
    for row in device.get("drift_status_history", []):
        if row.get("confirmed") or row.get("signals_fired"):
            return int(row["window_id"])
    return None


def _drift_duration_seconds(device: dict[str, Any], started_window: int | None) -> int:
    if started_window is None:
        return 0
    latest = device.get("trust_history", [])[-1].get("window_id", started_window) if device.get("trust_history") else started_window
    return max(0, int(latest - started_window + 1) * 5)


async def _similar_past_incidents(device_id: str) -> list[dict[str, Any]]:
    incidents = [i for i in await store.alerts() if i["device_id"] == device_id]
    return [{"window_id": i.get("window_id"), "description": f"Trust dropped to {i.get('trust')} with severity {i.get('severity')}."} for i in incidents[:-1][-3:]]


def _human_explanation(device: dict[str, Any], evidence: dict[str, Any]) -> str:
    name = device["device"]["name"]
    pattern = evidence.get("attack_pattern_match", "unknown")
    features = evidence.get("top_deviating_features", [])[:2]
    feature_text = ", ".join(f"{item['name']} at {item['z_score']} standard deviations from normal" for item in features) or "the latest features"
    duration = evidence.get("drift_duration_seconds", 0)
    return (
        f"{name} is flagged because {feature_text} changed away from its baseline. "
        f"The pattern currently resembles {pattern}, with drift ongoing for about {duration} seconds. "
        f"Treat this as evidence-led triage: confirm expected activity before isolating the device."
    )


def _estimated_impact(device_type: str) -> str:
    if device_type in {"lock"}:
        return "high"
    if device_type in {"camera", "doorbell", "tv", "thermostat"}:
        return "medium"
    return "low"


def _reversibility(device_type: str) -> str:
    if device_type in {"lock", "camera", "doorbell"}:
        return "requires_reonboarding"
    if device_type == "esp32":
        return "requires_factory_reset"
    return "fully_reversible"


def _remediation_rationale(device: dict[str, Any], evidence: dict[str, Any]) -> str:
    attack = evidence.get("attack_pattern_match", "unknown")
    name = device["device"]["name"]
    ip = device["device"]["ip"]
    severity = device["severity"]
    return (
        f"{name} ({ip}) is currently {severity} and the latest evidence is classified as {attack}. "
        "Blocking traffic contains the suspected behavior while the operator reviews logs, validates whether the activity is expected, and decides whether re-onboarding is needed."
    )


async def _related_devices(meta: dict[str, Any]) -> list[dict[str, Any]]:
    subnet = ".".join(str(meta["ip"]).split(".")[:3])
    related = []
    for device in await store.list_devices():
        same_subnet = str(device.get("ip", "")).startswith(f"{subnet}.")
        same_type = device.get("device_type") == meta["type"]
        if device["device_id"] != meta["device_id"] and (same_subnet or same_type):
            related.append(
                {
                    "device_id": device["device_id"],
                    "name": device["name"],
                    "ip": device["ip"],
                    "device_type": device["device_type"],
                    "reason": "same device_type" if same_type else "same subnet",
                    "current_trust": device["current_trust"],
                }
            )
    return related[:8]


async def _score_changes(minutes: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, minutes) * 60
    changes = []
    for summary in await store.list_devices():
        detail = await store.get_device(summary["device_id"])
        if not detail:
            continue
        rows = [row for row in detail.get("trust_history", []) if _timestamp(row.get("timestamp")) >= cutoff]
        if len(rows) < 2:
            continue
        delta = round(float(rows[-1]["trust"]) - float(rows[0]["trust"]), 2)
        changes.append({"device_id": summary["device_id"], "name": summary["name"], "from": rows[0]["trust"], "to": rows[-1]["trust"], "delta": delta})
    return sorted(changes, key=lambda row: abs(row["delta"]), reverse=True)[:5]


def _comparison_highlights(z_by_device: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    highlights = []
    for feature in FEATURE_NAMES:
        values = {device_id: scores.get(feature, 0.0) for device_id, scores in z_by_device.items()}
        spread = round(max(values.values()) - min(values.values()), 3) if values else 0.0
        highlights.append({"feature": feature, "z_score_spread": spread, "device_z_scores": values})
    return sorted(highlights, key=lambda row: abs(row["z_score_spread"]), reverse=True)[:5]


TOOL_REGISTRY: dict[str, ToolFunc] = {
    "list_flagged_devices": list_flagged_devices,
    "get_device_trust": get_device_trust,
    "explain_drift": explain_drift,
    "get_network_summary": get_network_summary,
    "system_remediation": system_remediation,
    "get_recent_activity": get_recent_activity,
    "compare_devices": compare_devices,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_flagged_devices",
            "description": "List devices currently below a trust threshold.",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {"type": "integer", "default": 70},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device_trust",
            "description": "Return rich device trust context: metadata, 30-window history, drift signals, baseline, latest 22 features, z-scores, alert timing, and peer comparison.",
            "parameters": {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": ["device_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_drift",
            "description": "Explain latest drift evidence, attack-pattern match, duration, similar incidents, confidence, and a deterministic human-readable explanation.",
            "parameters": {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": ["device_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_summary",
            "description": "Return aggregate network trust counts.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_remediation",
            "description": "Generate a block script, playbook, rationale, impact, reversibility, and related devices for human approval; does not execute anything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "platform": {"type": "string", "enum": ["iptables", "powershell"], "default": "iptables"},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_activity",
            "description": "Return network-wide alert timeline, top trust score changes, and dominant attack pattern over the last N minutes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "default": 10, "minimum": 1},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_devices",
            "description": "Compare 2-5 devices side by side by trust, severity, top deviating features, drift status, and differing z-score features.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 5,
                    },
                },
                "required": ["device_ids"],
            },
        },
    },
]


async def dispatch_tool(name: str, args: dict[str, Any]) -> Any:
    if name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool {name}."}
    try:
        return await TOOL_REGISTRY[name](**args)
    except ToolExecutionError as exc:
        return {"error": str(exc)}


def compact_json(value: Any, max_chars: int = 900) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."
