from __future__ import annotations


async def test_devices_returns_at_least_twelve(client, fresh_state):
    response = await client.get("/api/devices")
    assert response.status_code == 200
    assert len(response.json()) >= 12


async def test_device_summary_required_fields_and_ranges(client, fresh_state):
    devices = (await client.get("/api/devices")).json()
    severities = {"NORMAL", "WATCH", "AT_RISK", "CRITICAL"}
    for device in devices:
        assert {"device_id", "ip", "name", "device_type", "current_trust", "severity", "drift_confirmed"}.issubset(device)
        assert 0 <= device["current_trust"] <= 100
        assert device["severity"] in severities


async def test_device_detail_shape(client, fresh_state):
    response = await client.get("/api/devices/192.168.50.21")
    assert response.status_code == 200
    body = response.json()
    assert "trust_history" in body
    assert "drift_status" in body
    assert "behavioral_heatmap" in body
    assert isinstance(body["behavioral_heatmap"], list)


async def test_missing_device_returns_404(client, fresh_state):
    response = await client.get("/api/devices/nope")
    assert response.status_code == 404


async def test_evidence_card_shape(client, fresh_state):
    response = await client.get("/api/devices/192.168.50.21/evidence")
    assert response.status_code == 200
    evidence = response.json()
    assert isinstance(evidence["top_deviating_features"], list)
    assert {"name", "z_score"}.issubset(evidence["top_deviating_features"][0])


async def test_network_summary_counts_match_devices(client, fresh_state):
    devices = (await client.get("/api/devices")).json()
    summary = (await client.get("/api/network-summary")).json()
    assert summary["total_devices"] == len(devices)
    assert summary["healthy_count"] + summary["watch_count"] + summary["at_risk_count"] + summary["critical_count"] == len(devices)


async def test_alerts_reports_incidents_below_70(client, fresh_state, advance_simulator):
    await client.post("/api/scenario", json={"name": "slow_drift"})
    await advance_simulator(25)
    alerts = (await client.get("/api/alerts")).json()
    assert any(alert["device_id"] == "192.168.50.21" and alert["trust"] < 70 for alert in alerts)
