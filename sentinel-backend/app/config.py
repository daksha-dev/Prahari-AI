from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    SARVAM_API_KEY: str = ""
    SARVAM_BASE_URL: str = "https://api.sarvam.ai"
    SARVAM_MODEL: str = "sarvam-m"
    CORS_ORIGINS: str | list[str] = "http://localhost:5173,https://*.vercel.app"
    SIMULATOR_ENABLED: bool = True
    SIMULATOR_WINDOW_SECONDS: float = 5.0
    LOG_LEVEL: str = "INFO"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("SARVAM_MODEL", mode="before")
    @classmethod
    def normalize_sarvam_model(cls, value: str) -> str:
        if value == "sarvam-105b":
            return "sarvam-m"
        return value

    @property
    def sarvam_api_key(self) -> str:
        return self.SARVAM_API_KEY

    @property
    def sarvam_base_url(self) -> str:
        return self.SARVAM_BASE_URL

    @property
    def sarvam_model(self) -> str:
        return self.SARVAM_MODEL

    @property
    def cors_origins(self) -> list[str]:
        value = self.CORS_ORIGINS
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def simulator_enabled(self) -> bool:
        return self.SIMULATOR_ENABLED

    @property
    def simulator_window_seconds(self) -> float:
        return self.SIMULATOR_WINDOW_SECONDS

    @property
    def log_level(self) -> str:
        return self.LOG_LEVEL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
logger.info("Settings loaded from %s, key length: %s", ENV_FILE, len(settings.SARVAM_API_KEY))
