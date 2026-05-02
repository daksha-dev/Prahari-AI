from __future__ import annotations

import pytest

from app.ai.tools import (
    ToolExecutionError,
    compare_devices,
    explain_drift,
    get_device_trust,
    get_network_summary,
    get_recent_activity,
    list_flagged_devices,
    system_remediation,
)


async def test_list_flagged_devices_only_below_threshold(fresh_state, advance_simulator):
    from app.simulator.device_simulator import simulator

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    flagged = await list_flagged_devices(threshold=70)
    assert flagged
    assert all(device["current_trust"] < 70 for device in flagged)


async def test_list_flagged_devices_threshold_100_returns_all(fresh_state):
    flagged = await list_flagged_devices(threshold=100, limit=20)
    assert len(flagged) >= 12


async def test_list_flagged_devices_respects_limit(fresh_state):
    flagged = await list_flagged_devices(threshold=100, limit=3)
    assert len(flagged) == 3


async def test_get_device_trust_valid(fresh_state):
    status = await get_device_trust("192.168.50.21")
    assert status["device"]["device_id"] == "192.168.50.21"
    assert status["device"]["vendor"] == "generic"
    assert status["device"]["location"]
    assert "trust_history" in status
    assert {"window_id", "timestamp", "trust_score", "anomaly_score", "drift_factor"}.issubset(status["trust_history"][-1])
    assert len(status["current_window_features"]) == 22
    assert len(status["z_scores"]) == 22
    assert "bytes_per_sec" in status["baseline_summary"]
    assert "peer_comparison" in status


async def test_get_device_trust_invalid_raises(fresh_state):
    with pytest.raises(ToolExecutionError):
        await get_device_trust("missing")


async def test_explain_drift_valid(fresh_state):
    evidence = await explain_drift("192.168.50.21")
    assert evidence["top_deviating_features"]
    assert evidence["explanation"]
    assert evidence["attack_pattern_match"] in {
        "data_exfiltration",
        "lateral_scanning",
        "ddos_participation",
        "command_and_control",
        "frozen_sensor",
        "unknown",
    }
    assert 0 <= evidence["confidence"] <= 1
    assert "human_explanation" in evidence
    assert "drift_duration_seconds" in evidence


async def test_network_summary_counts_sum_to_total(fresh_state):
    summary = await get_network_summary()
    total = summary["healthy_count"] + summary["watch_count"] + summary["at_risk_count"] + summary["critical_count"]
    assert total == summary["total_devices"]


async def test_system_remediation_iptables(fresh_state):
    result = await system_remediation("192.168.50.21", "iptables")
    assert "192.168.50.21" in result["block_script"]
    assert "iptables -I" in result["block_script"]
    assert "DROP" in result["block_script"]
    assert len(result["playbook"]) == 3
    assert result["rationale"]
    assert result["estimated_impact"] in {"low", "medium", "high"}
    assert result["reversibility"] in {"fully_reversible", "requires_reonboarding", "requires_factory_reset"}
    assert isinstance(result["related_devices"], list)


async def test_system_remediation_powershell(fresh_state):
    result = await system_remediation("192.168.50.21", "powershell")
    assert "192.168.50.21" in result["block_script"]
    assert "New-NetFirewallRule" in result["block_script"]


async def test_system_remediation_invalid_platform(fresh_state):
    result = await system_remediation("192.168.50.21", "nftables")
    assert "Unsupported platform" in result["explanation"]


async def test_get_recent_activity_shape(fresh_state, advance_simulator):
    from app.simulator.device_simulator import simulator

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    activity = await get_recent_activity(minutes=10)
    assert "alert_timeline" in activity
    assert "score_changes" in activity
    assert "dominant_attack_pattern" in activity
    assert any(alert["device_id"] == "192.168.50.21" for alert in activity["alert_timeline"])


async def test_compare_devices_shape(fresh_state, advance_simulator):
    from app.simulator.device_simulator import simulator

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    comparison = await compare_devices(["192.168.50.21", "192.168.50.20"])
    assert len(comparison["devices"]) == 2
    assert comparison["highlights"]
    assert {"trust", "severity", "top_3_deviating_features", "drift_status"}.issubset(comparison["devices"][0])
