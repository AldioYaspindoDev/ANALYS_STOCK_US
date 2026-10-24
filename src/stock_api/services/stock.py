"""Stock information orchestration and in-memory TTL cache."""

import logging
import re
import threading
import time
from typing import Any

import yfinance as yf

from ..config import get_settings
from .market import get_market_data
from .news import get_headlines
from .sentiment import label_from_score, score_headlines

logger = logging.getLogger(__name__)
TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,5}(?:[.-][A-Z0-9]{1,5})?$")


class InvalidTickerError(ValueError):
    """Raised for ticker symbols outside the supported format."""


class StockInfoService:
    """Aggregate market, news, and sentiment data with a TTL cache."""

    def __init__(self, classifier: Any, ttl_seconds: int | None = None) -> None:
        self._classifier = classifier
        self._ttl = get_settings().cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get_info(self, ticker: str) -> dict[str, Any]:
        """Return ticker information, using a cached result when fresh."""
        symbol = ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(symbol):
            raise InvalidTickerError("Ticker tidak valid")

        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(symbol)
            if cached and cached[0] > now:
                return cached[1].copy()

        market_ticker = yf.Ticker(symbol)
        price, change_pct = get_market_data(symbol, market_ticker)
        headlines, source = get_headlines(market_ticker, symbol)
        try:
            score = score_headlines(headlines, self._classifier)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("FinBERT inference failed for %s: %s", symbol, type(exc).__name__)
            score = None
        result = {
            "ticker": symbol,
            "price": price,
            "change_pct": change_pct,
            "sentiment_label": label_from_score(score),
            "sentiment_score": None if score is None else round(score, 3),
            "news_count": len(headlines),
            "news_source": source,
            "top_headlines": headlines[:3],
        }
        with self._lock:
            self._cache[symbol] = (time.monotonic() + self._ttl, result)
        return result.copy()
