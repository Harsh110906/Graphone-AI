"""
Centralized configuration for the GraphOne ingestion engine.

All settings are loaded from environment variables (via .env file).
Uses pydantic-settings for validated, typed configuration.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogFormat(str, Enum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database ---
    database_url: str = "postgresql://graphone:graphone@localhost:5432/graphone"
    database_pool_size: int = 10

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- LLM Providers ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    # --- GitHub ---
    github_token: str = ""
    github_stars_cache_ttl_seconds: int = 86400  # 24 hours

    # --- Google Sheets ---
    google_sheets_credentials_path: str = ""
    google_sheet_id: str = ""

    # --- Object Storage (R2/S3) ---
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "graphone-raw"
    r2_endpoint_url: str = ""

    # --- Observability ---
    sentry_dsn: str = ""
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    # --- Crawler ---
    crawler_default_timeout_seconds: int = 30
    crawler_max_retries: int = 3
    crawler_per_domain_concurrency: int = 2
    crawler_user_agent: str = "GraphOneBot/1.0 (+https://graphone.ai/bot)"

    # --- Pipeline ---
    pipeline_batch_size: int = 100
    pipeline_max_workers: int = 4

    # --- Derived paths ---
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got '{v}'")
        return upper

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def seed_entities_path(self) -> Path:
        return self.data_dir / "seed_entities.json"

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_deepseek(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def has_github_token(self) -> bool:
        return bool(self.github_token)

    @property
    def has_sheets_credentials(self) -> bool:
        return bool(self.google_sheets_credentials_path) and bool(self.google_sheet_id)


# Singleton — import this from anywhere
settings = Settings()
