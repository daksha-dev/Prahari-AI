# Prahari Backend

FastAPI backend for an IoT trust-monitoring demo. It wraps a 22-feature trust analytics engine, runs a synthetic simulator for 12 devices, exposes REST polling endpoints, and provides a Sarvam-backed AI analyst over Server-Sent Events.

## Quick Start

```powershell
cd sentinel-backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Health check:

```powershell
curl http://localhost:8000/healthz
```

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `SARVAM_API_KEY` | empty | Required for `/api/chat` and AI summaries. REST endpoints work without it. |
| `SARVAM_BASE_URL` | `https://api.sarvam.ai` | Sarvam-compatible chat completions base URL. |
| `SARVAM_MODEL` | `sarvam-m` | Model sent in chat completion calls. Legacy `sarvam-105b` is normalized to `sarvam-m`. |
| `CORS_ORIGINS` | `http://localhost:5173,https://*.vercel.app` | Comma-separated allowed origins. |
| `SIMULATOR_ENABLED` | `true` | Starts the background synthetic simulator. |
| `SIMULATOR_WINDOW_SECONDS` | `5` | Demo-speed window interval. |
| `LOG_LEVEL` | `INFO` | Python logging level. |

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/healthz` | Railway health check. |
| `GET` | `/api/devices` | Device summaries with trust sparkline. |
| `GET` | `/api/devices/{id}` | Full device state, history, drift signals, and heatmap. |
| `GET` | `/api/devices/{id}/evidence` | Latest evidence card. |
| `GET` | `/api/devices/{id}/report?language=en` | Download an on-demand PDF incident report for a device. |
| `GET` | `/api/alerts` | Incidents where trust crossed below 70, newest first. |
| `GET` | `/api/network-summary` | Aggregate trust counts. |
| `POST` | `/api/scenario` | Switch simulator scenario and reset state. |
| `POST` | `/api/reset` | Reset demo state back to live mode. |
| `POST` | `/api/ingest` | Add or buffer ESP32 telemetry. |
| `POST` | `/api/chat` | SSE AI analyst endpoint. |

Switch scenarios:

```powershell
curl -X POST http://localhost:8000/api/scenario `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"slow_drift\"}"
```

Valid scenario names are `live`, `slow_drift`, `sudden_ddos`, and `recon_scan`.

## Chat SSE Example

```powershell
curl -N -X POST http://localhost:8000/api/chat `
  -H "Content-Type: application/json" `
  -d "{\"language\":\"en\",\"messages\":[{\"role\":\"user\",\"content\":\"Which devices are risky right now?\"}]}"
```

Each SSE event is JSON in the `data:` field:

```json
{"type":"token","content":"The "}
```

Tool-call events use `type: "tool_call"` and tool results use `type: "tool_result"`.

## Sarvam Configuration

Create an API key from `dashboard.sarvam.ai`, then set:

```powershell
$env:SARVAM_API_KEY="your_key"
$env:SARVAM_MODEL="sarvam-m"
$env:SARVAM_BASE_URL="https://api.sarvam.ai"
```

Verify chat:

```powershell
curl -N -X POST http://localhost:8000/api/chat `
  -H "Content-Type: application/json" `
  --data-binary "{\"messages\":[{\"role\":\"user\",\"content\":\"What devices should I worry about?\"}],\"language\":\"en\"}"
```

Without `SARVAM_API_KEY`, `/api/chat` emits an `error` SSE event, then the safe fallback response, then `done`. Sarvam failures are logged with full traceback at `ERROR` level.

## Testing

```powershell
pytest
pytest tests/test_simulator.py -v
pytest -v -s
pytest tests/test_smoke.py
```

The suite uses `TEST_MODE=1` to advance the simulator instantly without waiting for wall-clock demo windows.

## ESP32 Ingest Example

```powershell
curl -X POST http://localhost:8000/api/ingest `
  -H "Content-Type: application/json" `
  -d "{\"device_id\":\"192.168.50.99\",\"device_type\":\"esp32\",\"telemetry\":{\"temperature_c\":31.2,\"humidity_pct\":58,\"uptime_s\":1200,\"rssi\":-61}}"
```

## Engine Notes

The service uses the required 22 behavioral features. Isolation Forest trains on the first 30 synthetic windows per device and then freezes. River Half-Space Trees keeps updating online. ADWIN, chi-squared feature drift, and model disagreement combine into a 2-of-3 drift confirmation signal. Policy rules subtract direct penalties for high new destinations, high throughput, forbidden ports, and high SYN/ACK ratio.

The `slow_drift` scenario targets `192.168.50.21` and gradually pushes thermostat behavior away from baseline after scenario window 5, reaching critical trust around window 30 at the default demo cadence.

## Railway

```powershell
railway up
```

Railway uses `Procfile`, `railway.toml`, and `runtime.txt`. Set `SARVAM_API_KEY` in Railway variables before using chat.
