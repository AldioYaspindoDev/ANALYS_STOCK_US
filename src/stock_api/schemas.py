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


class HealthResponse(BaseModel):
    """Basic liveness response."""

    status: str
