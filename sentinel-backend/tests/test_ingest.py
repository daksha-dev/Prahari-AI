from __future__ import annotations


async def test_ingest_valid_esp32_adds_device(client, fresh_state):
    payload = {
        "device_id": "192.168.50.123",
        "device_type": "esp32",
        "telemetry": {"temperature_c": 31.2, "humidity_pct": 58, "uptime_s": 1200, "rssi": -61},
    }
    response = await client.post("/api/ingest", json=payload)
    assert response.status_code == 200
    devices = (await client.get("/api/devices")).json()
    assert any(device["device_id"] == "192.168.50.123" for device in devices)


async def test_ingest_malformed_payload_returns_422(client, fresh_state):
    response = await client.post("/api/ingest", json={"device_type": "esp32"})
    assert response.status_code == 422


async def test_ingest_buffers_telemetry(client, fresh_state):
    payload = {
        "device_id": "192.168.50.124",
        "device_type": "esp32",
        "telemetry": {"temperature_c": 30, "humidity_pct": 50, "uptime_s": 10, "rssi": -55},
    }
    await client.post("/api/ingest", json=payload)
    from app.store.memory_store import store

    assert len(store.telemetry_buffers["192.168.50.124"]) == 1
