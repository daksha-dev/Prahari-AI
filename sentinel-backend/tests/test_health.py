from __future__ import annotations

import importlib


async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_app_boots_without_sarvam_key(client, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    response = await client.get("/healthz")
    assert response.status_code == 200


async def test_app_boots_with_invalid_sarvam_key(client, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "not-a-real-key")
    response = await client.get("/healthz")
    assert response.status_code == 200


async def test_cors_preflight_devices(client):
    response = await client.options(
        "/api/devices",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
