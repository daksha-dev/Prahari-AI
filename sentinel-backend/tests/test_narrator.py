from __future__ import annotations

from app.ai.narrator import FALLBACK_NARRATION
from tests.conftest import FakeSarvamClient


async def test_manual_narration_is_cached_and_visible(client, fresh_state, advance_simulator, monkeypatch):
    from app.ai import narrator as narrator_module
    from app.simulator.device_simulator import simulator

    fake = FakeSarvamClient(
        scripts=[
            [
                {"choices": [{"delta": {"content": "The Smart Thermostat just dropped below trust 70. "}}]},
                {"choices": [{"delta": {"content": "Its destination and traffic behavior deviated from baseline. "}}]},
                {"choices": [{"delta": {"content": "This resembles reconnaissance or compromised firmware. Isolate it before reconnecting."}}]},
            ]
        ]
    )
    monkeypatch.setattr(narrator_module, "sarvam_client", fake)

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    first = await client.post("/api/devices/192.168.50.21/narrate")
    second = await client.post("/api/devices/192.168.50.21/narrate")
    detail = (await client.get("/api/devices/192.168.50.21")).json()

    assert first.status_code == 200
    assert second.json()["narration"] == first.json()["narration"]
    assert detail["narration"] == first.json()["narration"]
    assert len(fake.calls) == 1


async def test_narration_per_language(client, fresh_state, advance_simulator, monkeypatch):
    from app.ai import narrator as narrator_module
    from app.simulator.device_simulator import simulator
    from app.store.memory_store import store

    fake = FakeSarvamClient(
        scripts=[
            [{"choices": [{"delta": {"content": "English thermostat narration."}}]}],
            [{"choices": [{"delta": {"content": "हिंदी thermostat narration."}}]}],
        ]
    )
    monkeypatch.setattr(narrator_module, "sarvam_client", fake)

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    en = await client.post("/api/devices/192.168.50.21/narrate?language=en")
    hi = await client.post("/api/devices/192.168.50.21/narrate?language=hi")
    detail_en = (await client.get("/api/devices/192.168.50.21?language=en")).json()
    detail_hi = (await client.get("/api/devices/192.168.50.21?language=hi")).json()

    incident = await store.get_latest_incident("192.168.50.21")
    assert incident
    assert store.ai_summary_cache[("192.168.50.21", incident["window_id"], "en")] == en.json()["narration"]
    assert store.ai_summary_cache[("192.168.50.21", incident["window_id"], "hi")] == hi.json()["narration"]
    assert en.json()["narration"] != hi.json()["narration"]
    assert detail_en["narration"] == en.json()["narration"]
    assert detail_hi["narration"] == hi.json()["narration"]
    assert len(fake.calls) == 2


async def test_narration_skips_empty_choices_and_uses_valid_chunk(client, fresh_state, advance_simulator, monkeypatch):
    from app.ai import narrator as narrator_module
    from app.simulator.device_simulator import simulator

    fake = FakeSarvamClient(scripts=[[{"choices": []}, {"metadata": {"ignored": True}}, {"choices": [{"delta": {"content": "Valid narration."}}]}]])
    monkeypatch.setattr(narrator_module, "sarvam_client", fake)

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    response = await client.post("/api/devices/192.168.50.21/narrate")

    assert response.status_code == 200
    assert response.json()["narration"] == "Valid narration."


async def test_narration_all_empty_choices_returns_cached_fallback(client, fresh_state, advance_simulator, monkeypatch):
    from app.ai import narrator as narrator_module
    from app.simulator.device_simulator import simulator
    from app.store.memory_store import store

    fake = FakeSarvamClient(scripts=[[{"choices": []}, {"choices": []}]])
    monkeypatch.setattr(narrator_module, "sarvam_client", fake)

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    response = await client.post("/api/devices/192.168.50.21/narrate")
    incident = await store.get_latest_incident("192.168.50.21")

    assert response.status_code == 200
    assert response.json()["narration"] == FALLBACK_NARRATION
    assert incident
    assert store.ai_summary_cache[("192.168.50.21", incident["window_id"], "en")] == FALLBACK_NARRATION


async def test_alerts_survive_empty_choice_narration(client, fresh_state, advance_simulator, monkeypatch):
    from app.ai import narrator as narrator_module
    from app.simulator.device_simulator import simulator

    fake = FakeSarvamClient(scripts=[[{"choices": []}]])
    monkeypatch.setattr(narrator_module, "sarvam_client", fake)

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    response = await client.get("/api/alerts")

    assert response.status_code == 200
    assert any(alert["device_id"] == "192.168.50.21" and alert["ai_summary"] == FALLBACK_NARRATION for alert in response.json())


async def test_device_detail_survives_empty_choice_narration(client, fresh_state, advance_simulator, monkeypatch):
    from app.ai import narrator as narrator_module
    from app.simulator.device_simulator import simulator

    fake = FakeSarvamClient(scripts=[[{"choices": []}]])
    monkeypatch.setattr(narrator_module, "sarvam_client", fake)

    await simulator.switch_scenario("slow_drift")
    await advance_simulator(25)
    response = await client.get("/api/devices/192.168.50.21?language=en")

    assert response.status_code == 200
    assert response.json()["narration"] == FALLBACK_NARRATION
