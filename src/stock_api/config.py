"""Environment-backed application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for market, news, and sentiment processing."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    sentiment_threshold: float = 0.15
    max_news_items: int = 10
    news_http_timeout: float = 10.0
    news_user_agent: str = "stock-pipeline/1.0"
    finbert_model_name: str = "ProsusAI/finbert"
    cache_ttl_seconds: int = 300


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide environment settings."""
    return Settings()
