# Sarvam Chat Debug Notes

## What was wrong

- `sentinel-backend/.env` existed, but `SARVAM_API_KEY` was empty in this workspace.
- Settings loaded `.env` by relative path, so launching the backend from a different working directory could miss `sentinel-backend/.env`.
- `SarvamClient` captured cached settings at import time, making configuration changes invisible until restart.
- The default Sarvam model was `sarvam-105b`; the integration now defaults to `sarvam-m`.
- Chat fallback text hid the real exception behind a generic unavailable message.

## How it stays fixed

- `app.config.Settings` now loads the backend `.env` by absolute path.
- `SarvamClient` reads the API key at call time and also checks `os.environ`.
- Chat SSE error events expose the exception class and message.
- Unit tests cover mocked chat, tool-call streaming, language routing, config loading, error streaming, and model selection.
- Real Sarvam canaries are marked `sarvam_real` and skipped by default.

## Verification

```powershell
cd sentinel-backend
pytest
pytest -m sarvam_real
```

The real canary requires `SARVAM_API_KEY` to be set in the process environment. If the canary skips, no key was available to the test process.
