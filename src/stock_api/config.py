"""Environment-backed application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for market, news, and sentiment processing."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    sentiment_threshold: float = 0.15
    label_threshold: float = 0.15
    max_news_items: int = 10
    news_http_timeout: float = 10.0
    news_user_agent: str = "stock-pipeline/1.0"
    finbert_model_name: str = "ProsusAI/finbert"
    cache_ttl_seconds: int = 900
    cache_max_entries: int = 200
    finnhub_api_key: str = ""
    news_window_days: int = 7
    max_articles_per_source: int = 150
    max_articles_total: int = 200
    min_articles_for_label: int = 30
    fetch_timeout_seconds: int = 20
    http_timeout_seconds: float = 10.0
    http_user_agent: str = "Mozilla/5.0"
    dedupe_similarity: float = 0.9
    article_pos_threshold: float = 0.15
    half_life_days: float = 3.0
    finbert_max_length: int = 256
    finbert_batch_size: int = 16


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide environment settings."""
    return Settings()
