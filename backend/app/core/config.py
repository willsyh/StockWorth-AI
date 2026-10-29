"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = Field(default="development", description="development | production")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Supabase. When URL + anon key are set, persistence goes to Supabase and every
    # private endpoint requires a valid Supabase access token.
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # Local development fallback storage (SQLite), used only when Supabase is not configured.
    local_db_path: str = str(BACKEND_DIR / "data" / "stockworth_local.db")

    # AI provider. Leave the key empty to use deterministic rule-based insights only.
    ai_provider: str = "anthropic"  # anthropic | gemini
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    # Empty = the provider's default (claude-opus-5-5 / gemini-3.5-flash).
    ai_model: str = ""
    ai_timeout_seconds: float = 120.0
    ai_rate_limit_per_hour: int = 10

    max_upload_bytes: int = 2 * 1024 * 1024
    max_pdf_upload_bytes: int = 20 * 1024 * 1024

    # Market data (share prices). Leave the key empty to keep price entry manual only.
    market_data_provider: str = "alpha_vantage"
    alpha_vantage_api_key: str = ""
    market_cache_seconds: int = 900
    market_rate_limit_per_hour: int = 20

    @property
    def market_data_configured(self) -> bool:
        return self.market_data_provider == "alpha_vantage" and bool(self.alpha_vantage_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def ai_configured(self) -> bool:
        if self.ai_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.ai_provider == "gemini":
            return bool(self.gemini_api_key)
        return False

    @property
    def ai_model_name(self) -> str:
        if self.ai_model:
            return self.ai_model
        return {"anthropic": "claude-opus-5-5", "gemini": "gemini-3.5-flash"}.get(self.ai_provider, "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
