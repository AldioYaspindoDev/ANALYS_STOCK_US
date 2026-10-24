"""Pydantic response models."""

from pydantic import BaseModel


class StockInfoResponse(BaseModel):
    """Public response for a ticker information request."""

    ticker: str
    price: float
    change_pct: float
    sentiment_label: str
    sentiment_score: float | None
    news_count: int
    news_source: str
    top_headlines: list[str]
    positive_pct: float | None = None
    neutral_pct: float | None = None
    negative_pct: float | None = None
    sources_breakdown: dict[str, dict[str, int]] | None = None
    dropped_by_relevance: int = 0
    dropped_by_exact_dedupe: int = 0
    dropped_by_similarity_dedupe: int = 0
    dropped_no_date: int = 0
    dropped_out_of_window: int = 0
    source_errors: dict[str, str] | None = None
    articles_fetched: int = 0
    articles_after_dedupe: int = 0
    articles_scored: int = 0
    window_days: int = 7
    cached: bool = False


class HealthResponse(BaseModel):
    """Basic liveness response."""

    status: str
