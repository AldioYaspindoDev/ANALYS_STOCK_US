"""Market price retrieval."""

import logging
import math
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)


class MarketDataNotFoundError(LookupError):
    """Raised when no usable historical price data is available."""


def get_market_data(ticker: str, market_ticker: yf.Ticker | None = None) -> tuple[float, float]:
    """Return latest close and percentage change from the prior close."""
    try:
        history: Any = (market_ticker or yf.Ticker(ticker)).history(period="5d")
    except (yf.exceptions.YFException, OSError, TimeoutError, ValueError) as exc:
        logger.warning("Market data request failed for %s: %s", ticker, type(exc).__name__)
        raise MarketDataNotFoundError(ticker) from exc

    if history is None or history.empty or "Close" not in history:
        raise MarketDataNotFoundError(ticker)
    closes = history["Close"]
    latest = float(closes.iloc[-1])
    previous = float(closes.iloc[-2]) if len(closes) > 1 else latest
    if not math.isfinite(latest) or not math.isfinite(previous) or previous == 0:
        raise MarketDataNotFoundError(ticker)
    return round(latest, 2), round((latest - previous) / previous * 100, 2)
