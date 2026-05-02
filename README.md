# Sentinel Local Runbook

Sentinel is a local hackathon stack with a FastAPI backend, a Vite React frontend, a synthetic IoT simulator, REST polling endpoints, and a Sarvam-backed SSE chat analyst for investigating device trust, drift, alerts, and evidence.

## Quick Start

```powershell
.\start-dev.ps1
.\smoke-test.ps1
.\demo-check.ps1
```

## Setup

Put your Sarvam API key in `sentinel-backend/.env` by filling in `SARVAM_API_KEY=`. The frontend already points at the local backend through `sentinel-frontend/.env.local` with `VITE_API_URL=http://localhost:8000`.

## Project Structure

```text
sentinel/
├── sentinel-backend/    FastAPI + Sarvam + ML pipeline
├── sentinel-frontend/   React + Vite + Tailwind dashboard
├── hardware/            ESP32 firmware (optional demo prop)
├── docs/                PRD, deck, handbook
├── archive/             Pre-Vibe-a-thon prototype code (gitignored)
├── start-dev.ps1        Start both servers
├── smoke-test.ps1       Verify endpoints
└── demo-check.ps1       Walk the demo path
```

## Troubleshooting

If PowerShell blocks scripts, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

If port 8000 or 5173 is already in use, close old dev terminals or stop lingering processes:

```powershell
Get-Process node,python -ErrorAction SilentlyContinue | Stop-Process
```

If the browser shows a CORS error, verify `sentinel-backend/.env` contains:

```text
CORS_ORIGINS=http://localhost:5173,https://*.vercel.app
```
