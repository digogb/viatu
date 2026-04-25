"""Configurações lidas de .env via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = Field(default="postgresql+psycopg://latam:latam@localhost:5432/viatu")

    # Redis / Celery
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/1")

    # LATAM
    latam_base_url: str = Field(default="https://www.latamairlines.com")
    latam_cookies_path: str = Field(default=".latam_cookies.json")
    latam_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    )

    # Primer
    primer_headless: bool = Field(default=False)
    primer_timeout_ms: int = Field(default=60_000)

    # Evolution API
    evolution_base_url: str = Field(default="")
    evolution_instance: str = Field(default="")
    evolution_api_key: str = Field(default="")

    # App
    app_timezone: str = Field(default="America/Fortaleza")
    log_level: str = Field(default="INFO")
    alert_cooldown_hours: int = Field(default=12)
    default_interval_minutes: int = Field(default=30)


@lru_cache
def get_settings() -> Settings:
    return Settings()
