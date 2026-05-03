from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api import alerts, chat, devices, ingest, report
from app.config import ENV_FILE, settings
from app.models.schemas import ScenarioRequest
from app.simulator.device_simulator import simulator

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup cwd-sensitive env file resolved to %s", ENV_FILE)
    if settings.SARVAM_API_KEY:
        logger.info("SARVAM_API_KEY loaded (length: %s)", len(settings.SARVAM_API_KEY))
        try:
            from sarvamai import SarvamAI

            SarvamAI(api_subscription_key=settings.SARVAM_API_KEY)
            logger.info("Sarvam client initialized. Model: %s", settings.SARVAM_MODEL)
        except Exception as exc:
            logger.error("Sarvam client failed to initialize: %s: %s", type(exc).__name__, exc)
    else:
        logger.warning(
            "SARVAM_API_KEY is empty at boot.\n"
            "Resolved env file: %s\n"
            "File exists: %s. File size: %s bytes.\n"
            "Fix: set SARVAM_API_KEY=<actual_key> in sentinel-backend/.env and restart uvicorn.",
            ENV_FILE,
            ENV_FILE.exists(),
            ENV_FILE.stat().st_size if ENV_FILE.exists() else 0,
        )
    simulator.window_seconds = settings.simulator_window_seconds
    if settings.simulator_enabled:
        await simulator.start()
    yield
    if settings.simulator_enabled:
        await simulator.stop()


app = FastAPI(title="Prahari IoT Trust Backend", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(devices.router)
app.include_router(alerts.router)
app.include_router(chat.router)
app.include_router(ingest.router)
app.include_router(report.router)


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/scenario")
async def switch_scenario(payload: ScenarioRequest) -> dict[str, str | bool]:
    valid = {"live", "slow_drift", "sudden_ddos", "recon_scan"}
    if payload.name not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown scenario '{payload.name}'. Valid scenarios: {sorted(valid)}")
    await simulator.switch_scenario(payload.name)
    return {"ok": True, "scenario": payload.name}


@app.post("/api/reset")
async def reset_demo() -> dict[str, str | bool]:
    await simulator.switch_scenario("live")
    return {"ok": True, "scenario": "live"}
