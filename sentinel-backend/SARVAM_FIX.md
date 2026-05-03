# Sarvam API Key Loading Fix

## What Was Wrong

The original failure mode was an empty `SARVAM_API_KEY` value being parsed from `sentinel-backend/.env`. The app correctly resolved the env file path, but when the key line was empty the chat endpoint returned the configuration fallback.

The current diagnostic run no longer reproduces the empty-key state: `.env` contains one non-empty `SARVAM_API_KEY` line, `python-dotenv` reads it with length 36, and `pydantic-settings` reads the same value with length 36.

The `.env` file still contains the old `SARVAM_MODEL=sarvam-105b` value, so the config layer normalizes that legacy value to the valid `sarvam-m` model.

## Hardening Added

- `app/config.py` resolves `sentinel-backend/.env` with an absolute path.
- Env parsing uses `utf-8-sig` so a UTF-8 BOM cannot hide the first setting key.
- Settings are case-insensitive and ignore unrelated env values.
- Startup logs print the resolved env file path, `SARVAM_API_KEY` length, and model.
- If the key is empty at boot, the warning includes the env path, existence, file size, and one-line fix.
- `debug_env.py` prints byte-level and parser-level diagnostics.
- `tests/test_sarvam_integration.py::test_sarvam_key_actually_loaded` fails loudly when `.env` exists but the key is not loaded.

## Verification

Run:

```powershell
cd sentinel-backend
python debug_env.py
pytest
```

For the real Sarvam canary:

```powershell
pytest -m sarvam_real
```

Then restart uvicorn and confirm the boot log includes:

```text
SARVAM_API_KEY loaded (length: <non-zero>)
Sarvam client initialized. Model: sarvam-m
```
