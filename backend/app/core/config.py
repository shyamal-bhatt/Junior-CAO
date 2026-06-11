"""
core/config.py
──────────────
Central settings object powered by Pydantic-Settings.
All environment variables are read from the .env file at startup.
Add new config values here — never hardcode secrets in source files.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    App-wide settings. Values are loaded from environment variables
    (and the .env file). Pydantic validates types at startup so you
    get a clear error immediately if something is misconfigured.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME:     str = "Junior CAO API"
    APP_VERSION:  str = "0.1.0"
    APP_SITE_URL: str = "http://localhost:3000"
    DEBUG:        bool = False

    # ── Server ───────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    # ── OpenRouter ───────────────────────────────────────────────────────────
    # Get your key at https://openrouter.ai/keys
    OPENROUTER_API_KEY:    str = ""
    # Default model slug — can be overridden per-request by the frontend
    OPENROUTER_DEFAULT_MODEL: str = "openai/gpt-4o-mini"

    # ── Nango ────────────────────────────────────────────────────────────────
    NANGO_SECRET_KEY:      str = ""
    NANGO_SERVER_URL:      str = "https://api.nango.dev"

    # ── Supabase ─────────────────────────────────────────────────────────────
    SUPABASE_URL:          str = ""
    SUPABASE_KEY:          str = ""

    # ── OpenAI / Embeddings ──────────────────────────────────────────────────
    OPENAI_API_KEY:        str = ""


@lru_cache
def get_settings() -> Settings:
    """
    Returns the singleton Settings instance.
    @lru_cache means the .env file is parsed exactly once.

    Usage:
        from app.core.config import get_settings
        settings = get_settings()
    """
    return Settings()
