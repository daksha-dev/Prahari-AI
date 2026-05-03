from __future__ import annotations

import json

import pytest


def test_sarvam_key_actually_loaded():
    """If this test fails, the .env is not being read correctly."""
    from app.config import settings
    from pathlib import Path

    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        pytest.skip(".env not present in test environment")

    assert settings.SARVAM_API_KEY, (
        f"settings.SARVAM_API_KEY is empty even though {env_file} exists. "
        f"File size: {env_file.stat().st_size}. "
        f"Run `python debug_env.py` to diagnose."
    )
    assert len(settings.SARVAM_API_KEY) >= 8, (
        f"SARVAM_API_KEY length is {len(settings.SARVAM_API_KEY)} - looks invalid"
    )


class TestEnvFileResolution:
    def test_env_file_path_resolution(self):
        """Verify the resolved env_file path actually points to a real file."""
        from app.config import ENV_FILE

        assert ENV_FILE.exists(), f"Resolved env path {ENV_FILE} does not exist"
        assert ENV_FILE.is_file()

    def test_env_file_contains_sarvam_key(self):
        from app.config import ENV_FILE

        if not ENV_FILE.exists():
            pytest.skip("env file not present")
        content = ENV_FILE.read_text(encoding="utf-8")
        assert "SARVAM_API_KEY=" in content
        for line in content.splitlines():
            if line.startswith("SARVAM_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if not value:
                    pytest.skip(f"SARVAM_API_KEY in {ENV_FILE} is empty")
                return


class TestSettingsLoading:
    def test_settings_loads_key_from_env_file(self):
        from app.config import ENV_FILE, settings

        if not ENV_FILE.exists():
            pytest.skip("env file not present")
        env_content = ENV_FILE.read_text(encoding="utf-8")
        expected_key = None
        for line in env_content.splitlines():
            if line.startswith("SARVAM_API_KEY="):
                expected_key = line.split("=", 1)[1].strip()
                break
        if not expected_key:
            pytest.skip("SARVAM_API_KEY not set in env file")
        assert settings.SARVAM_API_KEY == expected_key, (
            f"Settings has wrong key. "
            f"Expected length {len(expected_key)}, got length {len(settings.SARVAM_API_KEY)}. "
            f"This means pydantic-settings is not reading the env file correctly."
        )


@pytest.mark.sarvam_real
class TestRealSarvamCall:
    async def test_chat_endpoint_returns_real_response(self, client):
        """End-to-end: chat endpoint must NOT return 'is not configured'."""
        from app.config import settings

        if not settings.SARVAM_API_KEY:
            pytest.skip("No key configured")

        body = {
            "messages": [{"role": "user", "content": "say hello"}],
            "language": "en",
        }
        response = await client.post("/api/chat", json=body)
        assert response.status_code == 200

        full_text = ""
        for line in response.text.splitlines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["type"] == "token":
                    full_text += event.get("content", "")
                elif event["type"] == "error":
                    pytest.fail(f"Got error event: {event}")

        assert "is not configured" not in full_text, (
            f"Got fallback message instead of real response. "
            f"This means SARVAM_API_KEY is not reaching the Sarvam client. "
            f"Full response: {full_text}"
        )
        assert len(full_text) > 0, "Got empty response from chat endpoint"
