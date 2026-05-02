from __future__ import annotations

from tests.conftest import parse_sse


async def test_end_to_end_happy_path(client, fresh_state, advance_simulator, mock_sarvam):
    assert (await client.get("/healthz")).status_code == 200
    devices = (await client.get("/api/devices")).json()
    assert len(devices) >= 12

    scenario = await client.post("/api/scenario", json={"name": "slow_drift"})
    assert scenario.status_code == 200
    await advance_simulator(25)

    thermostat = (await client.get("/api/devices/192.168.50.21")).json()
    assert thermostat["current_trust"] < 70

    evidence = (await client.get("/api/devices/192.168.50.21/evidence")).json()
    assert any(abs(item["z_score"]) > 2 for item in evidence["top_deviating_features"])

    response = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "Why is the thermostat flagged?"}], "language": "en"})
    events = parse_sse(response.text)
    assert any(event["type"] == "token" for event in events)
    assert events[-1]["type"] == "done"
