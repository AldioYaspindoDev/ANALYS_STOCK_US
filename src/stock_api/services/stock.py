"""Stock information orchestration and in-memory TTL cache."""

import logging
import re
import threading
import time
from collections import Counter
from typing import Any

import yfinance as yf

from ..config import get_settings
from .market import get_market_data
from .news import fetch_articles_for_symbol, sanitize_markdown
from .sentiment import aggregate_sentiment, label_from_score

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

    def _normalize_source(self, source: str) -> str:
        return sanitize_markdown(str(source).replace("_", "")).replace(" ", "")

    def get_info(self, ticker: str) -> dict[str, Any]:
        """Return ticker information, using a cached result when fresh."""
        symbol = ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(symbol):
            raise InvalidTickerError("Ticker tidak valid")

        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(symbol)
            if cached and cached[0] > now:
                cached_result = cached[1].copy()
                cached_result["cached"] = True
                return cached_result

        market_ticker = yf.Ticker(symbol)
        price, change_pct = get_market_data(symbol, market_ticker)
        try:
            info = getattr(market_ticker, "info", {})
            company_name = info.get("shortName", "") if isinstance(info, dict) else ""
        except (OSError, TimeoutError, ValueError, TypeError):
            company_name = ""

        try:
            articles, pipeline_summary, articles_fetched = fetch_articles_for_symbol(
                symbol, company_name
            )
            sentiment = aggregate_sentiment(articles, self._classifier)
            score = sentiment["sentiment_score"]
            final_sources = Counter(article.source for article in articles)
            source_names = [
                self._normalize_source(name)
                for name, count in final_sources.items()
                if count > 0
            ]
            news_source = ", ".join(source_names).strip(", ") or "none"
            result = {
                "ticker": symbol,
                "price": price,
                "change_pct": change_pct,
                "sentiment_label": sentiment["sentiment_label"],
                "sentiment_score": score,
                "news_count": sentiment["news_count"],
                "news_source": news_source,
                "top_headlines": sentiment["top_headlines"],
                "positive_pct": sentiment["positive_pct"],
                "neutral_pct": sentiment["neutral_pct"],
                "negative_pct": sentiment["negative_pct"],
                "sources_breakdown": {
                    "fetched": {
                        self._normalize_source(key): value
                        for key, value in pipeline_summary["fetched"].items()
                        if value > 0
                    },
                    "after_relevance": {
                        self._normalize_source(key): value
                        for key, value in pipeline_summary["after_relevance"].items()
                        if value > 0
                    },
                    "after_dedupe": {
                        self._normalize_source(key): value
                        for key, value in pipeline_summary["after_dedupe"].items()
                        if value > 0
                    },
                },
                "dropped_by_relevance": pipeline_summary["dropped_by_relevance"],
                "dropped_by_exact_dedupe": pipeline_summary["dropped_by_exact_dedupe"],
                "dropped_by_similarity_dedupe": pipeline_summary[
                    "dropped_by_similarity_dedupe"
                ],
                "dropped_no_date": pipeline_summary["dropped_no_date"],
                "dropped_out_of_window": pipeline_summary["dropped_out_of_window"],
                "source_errors": {
                    self._normalize_source(key): value
                    for key, value in pipeline_summary["source_errors"].items()
                },
                "articles_fetched": articles_fetched,
                "articles_after_dedupe": len(articles),
                "articles_scored": sentiment["articles_scored"],
                "window_days": get_settings().news_window_days,
                "cached": False,
            }
        except Exception as exc:  # pragma: no cover
            logger.warning("Stock info pipeline failed for %s: %s", symbol, type(exc).__name__)
            score = None
            result = {
                "ticker": symbol,
                "price": price,
                "change_pct": change_pct,
                "sentiment_label": label_from_score(score),
                "sentiment_score": score,
                "news_count": 0,
                "news_source": "none",
                "top_headlines": [],
                "positive_pct": 0.0,
                "neutral_pct": 0.0,
                "negative_pct": 0.0,
                "sources_breakdown": {
                    "fetched": {},
                    "after_relevance": {},
                    "after_dedupe": {},
                },
                "dropped_by_relevance": 0,
                "dropped_by_exact_dedupe": 0,
                "dropped_by_similarity_dedupe": 0,
                "dropped_no_date": 0,
                "dropped_out_of_window": 0,
                "source_errors": {},
                "articles_fetched": 0,
                "articles_after_dedupe": 0,
                "articles_scored": 0,
                "window_days": get_settings().news_window_days,
                "cached": False,
            }

        with self._lock:
            self._cache[symbol] = (time.monotonic() + self._ttl, result)
        return result.copy()
