from __future__ import annotations

import pytest


async def trust_for(client, device_id: str) -> float:
    return (await client.get(f"/api/devices/{device_id}")).json()["current_trust"]


async def test_live_devices_stay_healthy(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "live"})
    await advance_simulator(30)
    devices = (await client.get("/api/devices")).json()
    assert all(device["current_trust"] >= 70 for device in devices)


async def test_slow_drift_thermostat_trajectory(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "slow_drift"})
    await advance_simulator(5)
    after_5 = await trust_for(client, "192.168.50.21")
    await advance_simulator(15)
    after_20 = await trust_for(client, "192.168.50.21")
    await advance_simulator(10)
    after_30 = await trust_for(client, "192.168.50.21")
    assert after_5 >= 80
    assert after_20 < 70
    assert after_30 < 50
    assert after_5 > after_20 > after_30


async def test_slow_drift_populates_narration_after_threshold_crossing(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "slow_drift"})
    crossed = False
    for _ in range(30):
        await advance_simulator(1)
        detail = (await client.get("/api/devices/192.168.50.21")).json()
        if detail["current_trust"] < 70:
            crossed = True
            await advance_simulator(2)
            narrated = (await client.get("/api/devices/192.168.50.21")).json()
            assert narrated["narration"]
            break
    assert crossed


async def test_slow_drift_confirmed_between_15_and_30(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "slow_drift"})
    confirmed_at = None
    for window in range(1, 31):
        await advance_simulator(1)
        detail = (await client.get("/api/devices/192.168.50.21")).json()
        if detail["device"]["drift_confirmed"]:
            confirmed_at = window
            break
    assert confirmed_at is not None
    assert 15 <= confirmed_at <= 30


async def test_sudden_ddos_camera_drops_within_five_windows(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "sudden_ddos"})
    start = await trust_for(client, "192.168.50.04")
    await advance_simulator(5)
    end = await trust_for(client, "192.168.50.04")
    assert end < start - 10


async def test_recon_scan_new_dst_spike(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "recon_scan"})
    await advance_simulator(8)
    evidence = (await client.get("/api/devices/192.168.50.15/evidence")).json()
    assert any(item["name"] == "new_dst_count" for item in evidence["top_deviating_features"])
    assert any(v["rule"] == "new_dst_count" for v in evidence["policy_violations"])


async def test_invalid_scenario_returns_400(client, fresh_state):
    response = await client.post("/api/scenario", json={"name": "bad"})
    assert response.status_code == 400
    assert "Unknown scenario" in response.json()["detail"]


async def test_scenario_switch_resets_state(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "slow_drift"})
    await advance_simulator(25)
    drifted = await trust_for(client, "192.168.50.21")
    await client.post("/api/scenario", json={"name": "live"})
    reset = await trust_for(client, "192.168.50.21")
    assert drifted < 70
    assert reset >= 90


async def test_advance_guard_disabled(monkeypatch, fresh_state):
    from app.simulator.device_simulator import simulator

    monkeypatch.delenv("TEST_MODE", raising=False)
    with pytest.raises(RuntimeError):
        await simulator.advance(1)
    monkeypatch.setenv("TEST_MODE", "1")
