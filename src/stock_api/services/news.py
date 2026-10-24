"""News retrieval, parsing, and deduplication."""

import logging
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

import requests
import yfinance as yf

from ..config import get_settings

logger = logging.getLogger(__name__)


def headlines_from_yfinance(ticker: yf.Ticker) -> list[str]:
    """Parse headline strings from both supported yfinance news formats."""
    try:
        items = ticker.news or []
    except (OSError, TimeoutError, ValueError) as exc:
        logger.warning("yfinance news request failed: %s", type(exc).__name__)
        return []
    titles: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        title = item.get("title") or (content.get("title") if isinstance(content, dict) else None)
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return titles


def headlines_from_google_news(query: str) -> list[str]:
    """Fetch and parse headline titles from Google News RSS."""
    settings = get_settings()
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}+when:7d&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        response = requests.get(
            url,
            timeout=settings.news_http_timeout,
            headers={"User-Agent": settings.news_user_agent},
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError, OSError) as exc:
        logger.warning("Google News request or RSS parsing failed: %s", type(exc).__name__)
        return []

    titles: list[str] = []
    for item in root.iter("item"):
        title = item.findtext("title")
        if title:
            cleaned = title.rsplit(" - ", 1)[0].strip()
            if cleaned:
                titles.append(cleaned)
    return titles


def dedupe(titles: list[str]) -> list[str]:
    """Remove duplicate titles case-insensitively, preserving order."""
    seen: set[str] = set()
    unique: list[str] = []
    for title in titles:
        key = title.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(title)
    return unique


def get_headlines(ticker: yf.Ticker, symbol: str) -> tuple[list[str], str]:
    """Get preferred headlines, falling back to Google News when needed."""
    limit = get_settings().max_news_items
    titles = dedupe(headlines_from_yfinance(ticker))
    if titles:
        logger.info("News source selected: yfinance")
        return titles[:limit], "yfinance"

    try:
        info: Any = ticker.info
        company_name = info.get("shortName", "") if isinstance(info, dict) else ""
    except (OSError, TimeoutError, ValueError) as exc:
        logger.warning("Company metadata request failed: %s", type(exc).__name__)
        company_name = ""
    query = f"{company_name} {symbol} stock".strip()
    titles = dedupe(headlines_from_google_news(query))
    source = "google_news" if titles else "none"
    logger.info("News source selected: %s", source)
    return titles[:limit], source
