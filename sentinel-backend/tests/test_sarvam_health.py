import os

import pytest
from sarvamai import SarvamAI


@pytest.mark.sarvam_real
def test_sarvam_actually_works():
    """Smoke test: hit the real Sarvam API. Skipped if no key."""
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        pytest.skip("SARVAM_API_KEY not set")
    client = SarvamAI(api_subscription_key=key)
    response = client.chat.completions(
        model="sarvam-m",
        messages=[{"role": "user", "content": "say hello in one word"}],
        max_tokens=10,
    )
    assert response.choices[0].message.content
    assert len(response.choices[0].message.content) > 0
