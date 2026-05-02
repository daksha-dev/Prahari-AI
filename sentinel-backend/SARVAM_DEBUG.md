# Sarvam Configuration Debug Notes

## Diagnostic findings

- `app.config.ENV_FILE` resolves to `C:\Users\daksh\MyLife\Studies\IITM\Eclipse-Hackathon\Code\sentinel-backend\.env`.
- The resolved `.env` file exists and was used as the settings `env_file`.
- Before the fix, `Settings()` still produced `SARVAM_API_KEY` length `0`.
- `SarvamClient.api_key` was empty immediately before SDK client construction, so the failure was upstream of the Sarvam SDK call.
- The only source occurrence of the old `"SARVAM_API_KEY is not configured."` message was in `app/ai/sarvam_client.py`.
- In this local checkout, direct reading of the current `.env` also showed the `SARVAM_API_KEY=` line value length as `0`; `.env` was not modified by this fix.

## Code fixes

- `app/config.py` now computes `ENV_FILE` from `__file__` and passes it to `pydantic-settings` as an absolute string path.
- The settings schema uses the environment variable names as canonical fields and exposes lowercase properties for existing app code.
- `app/config.py` creates a module-level `settings` instance and logs the resolved env file path and key length at module load.
- `app/ai/sarvam_client.py` now raises a diagnostic `SarvamUnavailable` message when the key is empty, including the resolved env path, file existence, and file size.
- `app/api/chat.py` logs `SarvamUnavailable` with traceback and emits an SSE error event plus a visible diagnostic token.
- `app/main.py` runs a startup Sarvam client construction check when a key is present and logs the configured model.

## Verification

Run these from `sentinel-backend/`:

```powershell
pytest tests/test_sarvam_integration.py -v
pytest -m sarvam_real
pytest
```

Manual endpoint check:

```powershell
'{"messages":[{"role":"user","content":"hello"}],"language":"en"}' | Out-File -Encoding ascii t.json
curl.exe -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" --data-binary "@t.json"
```

If the key is empty or unreadable, the response now includes the exact env file path, whether it exists, and its size.
