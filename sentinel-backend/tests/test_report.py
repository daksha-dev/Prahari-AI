from __future__ import annotations

import re

import app.api.report as report_module


async def _fake_narration(device_id: str, language: str = "en") -> str:
    return f"Generated {language} incident narrative for {device_id}. The device behavior changed from its baseline and should be reviewed."


async def test_report_returns_pdf(client, fresh_state, monkeypatch):
    monkeypatch.setattr(report_module, "narrate_device", _fake_narration)

    response = await client.get("/api/devices/192.168.50.21/report")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 5_000


async def test_report_filename(client, fresh_state, monkeypatch):
    monkeypatch.setattr(report_module, "narrate_device", _fake_narration)

    response = await client.get("/api/devices/192.168.50.21/report")

    disposition = response.headers["content-disposition"]
    assert re.match(r'attachment; filename="prahari-192\.168\.50\.21-\d{8}T\d{6}Z\.pdf"', disposition)


async def test_report_for_unknown_device_returns_404(client, fresh_state):
    response = await client.get("/api/devices/not-a-device/report")

    assert response.status_code == 404


async def test_report_in_hindi(client, fresh_state, monkeypatch):
    monkeypatch.setattr(report_module, "narrate_device", _fake_narration)

    response = await client.get("/api/devices/192.168.50.21/report?language=hi")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert len(response.content) > 5_000
