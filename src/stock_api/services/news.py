"""News retrieval, parsing, deduplication, and relevance filtering."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import requests
import yfinance as yf

from ..config import get_settings

logger = logging.getLogger(__name__)
_FINANCIAL_KEYWORDS = (
    "stock",
    "stocks",
    "shares",
    "earnings",
    "guidance",
    "finance",
    "markets",
    "investors",
    "revenue",
)


@dataclass
class Article:
    """Normalized news article representation."""

    title: str
    summary: str
    source: str
    publisher: str
    url: str
    published_at: datetime | None = None


def sanitize_markdown(value: str) -> str:
    """Remove Telegram Markdown control characters and normalize spacing."""
    cleaned = str(value or "")
    replacements = {
        "_": " ",
        "*": " ",
        "[": "(",
        "]": ")",
        "`": "",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return " ".join(cleaned.split())


def _normalize_title(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", (value or "").casefold()).strip()


def _normalize_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    query_pairs: list[tuple[str, str]] = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower().startswith("utm_"):
            continue
        query_pairs.append((key, val))
    cleaned = urlunsplit(
        parsed._replace(
            query=urlencode(query_pairs, doseq=True),
            fragment="",
        )
    )
    return cleaned.rstrip("/")


def _source_label(name: str) -> str:
    return sanitize_markdown(str(name).replace("_", "").replace(" ", "")).replace(" ", "")


def _canonical_article(article: Article) -> tuple[float, datetime | None]:
    published = article.published_at or datetime.min.replace(tzinfo=timezone.utc)
    summary_score = 1.0 if article.summary.strip() else 0.0
    return (summary_score, published)


def _is_similar_title(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return SequenceMatcher(None, _normalize_title(left), _normalize_title(right)).ratio() >= 0.9


def dedupe(titles: list[str]) -> list[str]:
    """Remove duplicate headlines while preserving the first occurrence."""
    seen: set[str] = set()
    unique: list[str] = []
    for title in titles:
        normalized = title.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def dedupe_articles(articles: list[Article]) -> list[Article]:
    """Remove exact duplicates and near-duplicate headlines while keeping the richest entry."""
    unique, _, _ = dedupe_articles_with_stats(articles)
    return unique


def dedupe_articles_with_stats(
    articles: list[Article],
) -> tuple[list[Article], int, int]:
    """Return deduped items and the exact/similarity duplicate counts."""
    unique: list[Article] = []
    exact_drops = 0
    similarity_drops = 0
    for article in articles:
        duplicate_index = None
        duplicate_kind = ""
        normalized_url = _normalize_url(article.url)
        normalized_title = _normalize_title(article.title)
        for idx, current in enumerate(unique):
            current_url = _normalize_url(current.url)
            current_title = _normalize_title(current.title)
            if normalized_url and current_url and normalized_url == current_url:
                duplicate_index = idx
                duplicate_kind = "exact"
                break
            if normalized_title and current_title and normalized_title == current_title:
                duplicate_index = idx
                duplicate_kind = "exact"
                break
            if _is_similar_title(article.title, current.title):
                duplicate_index = idx
                duplicate_kind = "similar"
                break

        if duplicate_index is None:
            unique.append(article)
            continue

        if duplicate_kind == "similar":
            similarity_drops += 1
        else:
            exact_drops += 1
        if _canonical_article(article) > _canonical_article(unique[duplicate_index]):
            unique[duplicate_index] = article
    return unique, exact_drops, similarity_drops


def filter_relevant_articles(
    articles: list[Article], company_name: str = "", ticker: str = ""
) -> list[Article]:
    """Keep only articles mentioning the company or ticker as a standalone token."""
    relevant, _, _ = filter_relevant_articles_with_stats(articles, company_name, ticker)
    return relevant


def filter_relevant_articles_with_stats(
    articles: list[Article], company_name: str = "", ticker: str = ""
) -> tuple[list[Article], list[str], int]:
    """Return the relevant subset plus the dropped sample list and drop count."""
    company = re.sub(
        r"\b(?:Inc|Corp|Corporation|Ltd|Limited|LLC)\b\.?",
        "",
        company_name,
        flags=re.IGNORECASE,
    )
    company = company.strip()
    text_parts = [company, ticker]
    needle_values = [part for part in text_parts if isinstance(part, str) and part and part.strip()]
    if not needle_values:
        return list(articles), [], 0

    relevant: list[Article] = []
    dropped_titles: list[str] = []
    for article in articles:
        haystack = f"{article.title} {article.summary}".lower()
        matched = False
        for needle in needle_values:
            token = re.escape(needle.lower())
            pattern = rf"(?<![a-z0-9]){token}(?![a-z0-9])"
            if re.search(pattern, haystack):
                matched = True
                break
            if len(needle) <= 3 and any(keyword in haystack for keyword in _FINANCIAL_KEYWORDS):
                if re.search(pattern, haystack):
                    matched = True
                    break

        if matched:
            relevant.append(article)
        else:
            dropped_titles.append(article.title)
    return relevant, dropped_titles, len(dropped_titles)


def headlines_from_yfinance(ticker: yf.Ticker) -> list[str]:
    """Compatibility wrapper returning deduplicated headline strings for yfinance."""
    titles: list[str] = []
    try:
        items = ticker.news or []
    except (OSError, TimeoutError, ValueError, AttributeError) as exc:
        logger.warning("yfinance news request failed: %s", type(exc).__name__)
        return []

    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        title = item.get("title") or content.get("title")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return dedupe(titles)


def fetch_yfinance_articles(ticker: yf.Ticker) -> list[Article]:
    """Parse article objects from both supported yfinance news formats."""
    try:
        items = ticker.news or []
    except (OSError, TimeoutError, ValueError, AttributeError) as exc:
        logger.warning("yfinance news request failed: %s", type(exc).__name__)
        return []

    articles: list[Article] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        title = item.get("title") or content.get("title")
        summary = item.get("summary") or content.get("summary") or ""
        url = item.get("link") or item.get("url") or content.get("link") or ""
        publisher = item.get("publisher") or content.get("publisher") or ""
        timestamp = (
            item.get("providerPublishTime")
            or item.get("published_at")
            or content.get("providerPublishTime")
        )
        published_at = None
        if isinstance(timestamp, (int, float)):
            published_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        elif isinstance(timestamp, str):
            try:
                published_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
            except ValueError:
                published_at = None
        if not isinstance(title, str) or not title.strip():
            continue
        articles.append(
            Article(
                title=title.strip(),
                summary=str(summary).strip(),
                source="yfinance",
                publisher=str(publisher).strip() or "yfinance",
                url=url,
                published_at=published_at,
            )
        )
    return articles


def headlines_from_google_news(query: str, session: requests.Session | None = None) -> list[str]:
    """Compatibility wrapper returning deduplicated Google News headlines."""
    settings = get_settings()
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}+when:{settings.news_window_days}d&hl=en-US&gl=US&ceid=US:en"
    )
    request_session = session or requests.Session()
    try:
        if session is None:
            response = requests.get(
                url,
                timeout=settings.http_timeout_seconds,
                headers={"User-Agent": settings.http_user_agent},
            )
        else:
            response = request_session.get(
                url,
                timeout=settings.http_timeout_seconds,
                headers={"User-Agent": settings.http_user_agent},
            )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError, OSError, ValueError) as exc:
        logger.warning("Google News request or RSS parsing failed: %s", type(exc).__name__)
        return []

    titles: list[str] = []
    for item in root.iter("item"):
        title = item.findtext("title")
        if title:
            cleaned = title.rsplit(" - ", 1)[0].strip()
            if cleaned:
                titles.append(cleaned)
    return dedupe(titles)


def fetch_google_news_articles(
    query: str, session: requests.Session | None = None
) -> list[Article]:
    """Fetch and parse article objects from Google News RSS."""
    settings = get_settings()
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}+when:{settings.news_window_days}d&hl=en-US&gl=US&ceid=US:en"
    )
    request_session = session or requests.Session()
    try:
        response = request_session.get(
            url,
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError, OSError, ValueError) as exc:
        logger.warning("Google News request or RSS parsing failed: %s", type(exc).__name__)
        return []

    articles: list[Article] = []
    for item in root.iter("item"):
        title = item.findtext("title")
        description = item.findtext("description") or ""
        link = item.findtext("link") or ""
        if not title:
            continue
        cleaned = title.rsplit(" - ", 1)[0].strip()
        if not cleaned:
            continue
        published_at = None
        pub_date = item.findtext("pubDate")
        if pub_date:
            try:
                published_at = parsedate_to_datetime(pub_date)
            except (TypeError, ValueError, IndexError):
                published_at = None
        articles.append(
            Article(
                title=cleaned,
                summary=description,
                source="googlenews",
                publisher=(item.findtext("source") or "google news").strip(),
                url=link,
                published_at=published_at,
            )
        )
    return articles


def fetch_finnhub_articles(symbol: str, session: requests.Session) -> list[Article]:
    """Fetch news articles from Finnhub company-news endpoint."""
    settings = get_settings()
    api_key = settings.finnhub_api_key.strip()
    if not api_key:
        logger.warning("FINNHUB_API_KEY is empty; skipping Finnhub news source")
        return []
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (
        datetime.utcnow() - timedelta(days=settings.news_window_days)
    ).strftime("%Y-%m-%d")
    url = (
        "https://finnhub.io/api/v1/company-news?"
        f"symbol={symbol}&from={start_date}&to={end_date}&token={api_key}"
    )
    try:
        response = session.get(url, timeout=settings.http_timeout_seconds)
        if response.status_code in {401, 403}:
            logger.warning("Finnhub authentication failed for %s", symbol)
            return []
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("Finnhub news request failed for %s: %s", symbol, type(exc).__name__)
        return []

    articles: list[Article] = []
    for item in payload[: settings.max_articles_per_source]:
        raw_title = item.get("headline") or ""
        summary = item.get("summary") or ""
        url_value = item.get("url") or ""
        source = item.get("source") or "finnhub"
        timestamp = item.get("datetime")
        published_at = None
        if isinstance(timestamp, (int, float)):
            numeric_ts = float(timestamp)
            seconds = numeric_ts / 1000 if numeric_ts > 1_000_000_000_000 else numeric_ts
            published_at = datetime.fromtimestamp(seconds, tz=timezone.utc)
        if raw_title.strip():
            articles.append(
                Article(
                    title=raw_title.strip(),
                    summary=str(summary).strip(),
                    source="finnhub",
                    publisher=str(source).strip() or "finnhub",
                    url=url_value,
                    published_at=published_at,
                )
            )
    return articles


def fetch_gdelt_articles(
    company_name: str, symbol: str, session: requests.Session
) -> list[Article]:
    """Fetch news articles from the GDELT DOC 2.0 API."""
    settings = get_settings()
    query = f'"{company_name or symbol}" sourcelang:english'
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": settings.max_articles_per_source,
        "sort": "datedesc",
        "timespan": str(settings.news_window_days),
    }
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(params)
    try:
        response = session.get(url, timeout=settings.http_timeout_seconds)
        if response.status_code == 429:
            logger.warning("GDELT rate-limited for %s; skipping", symbol)
            return []
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type and not response.text.lstrip().startswith("{"):
            logger.warning("GDELT returned non-JSON content for %s", symbol)
            return []
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("GDELT news request failed for %s: %s", symbol, type(exc).__name__)
        return []

    articles: list[Article] = []
    for item in payload.get("articles", [])[: settings.max_articles_per_source]:
        title = item.get("title") or ""
        url_value = item.get("url") or ""
        published_raw = item.get("seendate") or ""
        published_at = None
        if published_raw:
            try:
                published_at = datetime.strptime(
                    published_raw, "%Y%m%dT%H%M%SZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                published_at = None
        if title.strip():
            articles.append(
                Article(
                    title=title.strip(),
                    summary="",
                    source="gdelt",
                    publisher=str(item.get("domain") or "gdelt").strip() or "gdelt",
                    url=url_value,
                    published_at=published_at,
                )
            )
    return articles


def filter_articles_by_window(articles: list[Article]) -> tuple[list[Article], int, int]:
    """Keep articles inside the configured window and count missing dates."""
    settings = get_settings()
    kept: list[Article] = []
    dropped_no_date = 0
    dropped_out_of_window = 0
    now = datetime.now(timezone.utc)
    for article in articles:
        if article.published_at is None:
            dropped_no_date += 1
            kept.append(article)
            continue
        age_days = (now - article.published_at).total_seconds() / 86400
        if age_days > settings.news_window_days:
            dropped_out_of_window += 1
            continue
        kept.append(article)
    return kept, dropped_no_date, dropped_out_of_window


def fetch_articles_for_symbol(
    symbol: str, company_name: str | None = None
) -> tuple[list[Article], dict[str, Any], int]:
    """Fetch news from all configured sources in parallel, then merge results."""
    settings = get_settings()
    session = requests.Session()
    session.headers.update({"User-Agent": settings.http_user_agent})
    company = company_name or symbol

    def _safe(source_name: str, func, *args):
        try:
            result = func(*args)
            if result is None:
                return [], "empty result"
            return result, None
        except (
            requests.RequestException,
            ValueError,
            ET.ParseError,
            KeyError,
            TypeError,
            OSError,
        ) as exc:
            logger.warning(
                "%s source failed for %s: %s",
                source_name,
                symbol,
                type(exc).__name__,
            )
            return [], f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(_safe, "finnhub", fetch_finnhub_articles, symbol, session): "finnhub",
            executor.submit(
                _safe,
                "googlenews",
                fetch_google_news_articles,
                f"{company} {symbol} stock".strip(),
                session,
            ): "googlenews",
            executor.submit(
                _safe, "gdelt", fetch_gdelt_articles, company, symbol, session
            ): "gdelt",
            executor.submit(
                _safe, "yfinance", fetch_yfinance_articles, yf.Ticker(symbol)
            ): "yfinance",
        }
        fetched_by_source: dict[str, list[Article]] = {}
        source_errors: dict[str, str] = {}
        all_articles: list[Article] = []
        for future in as_completed(future_map):
            source_name = future_map[future]
            try:
                fetched, error_reason = future.result()
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "%s source raised unexpected exception for %s: %s",
                    source_name,
                    symbol,
                    type(exc).__name__,
                )
                fetched = []
                error_reason = f"{type(exc).__name__}"
            fetched = fetched or []
            fetched_by_source[source_name] = fetched
            if error_reason:
                source_errors[source_name] = error_reason
            elif not fetched:
                source_errors[source_name] = "empty result"
            all_articles.extend(fetched)

    fetched_stage = {
        source: len(items) for source, items in fetched_by_source.items()
    }
    filtered_by_window, dropped_no_date, dropped_out_of_window = (
        filter_articles_by_window(all_articles)
    )
    relevant_articles, dropped_titles, relevance_drop_count = (
        filter_relevant_articles_with_stats(filtered_by_window, company_name or "", symbol)
    )
    if logger.isEnabledFor(logging.DEBUG) and dropped_titles:
        logger.debug(
            "Dropped by relevance (%s): %s",
            symbol,
            ", ".join(dropped_titles[:10]),
        )

    deduped, exact_drops, similarity_drops = dedupe_articles_with_stats(relevant_articles)
    final_by_source = Counter(article.source for article in deduped)
    after_relevance = Counter(article.source for article in relevant_articles)
    after_dedupe = {source: count for source, count in final_by_source.items()}
    pipeline_summary = {
        "fetched": fetched_stage,
        "after_relevance": {source: count for source, count in after_relevance.items()},
        "after_dedupe": after_dedupe,
        "dropped_by_relevance": relevance_drop_count,
        "dropped_by_exact_dedupe": exact_drops,
        "dropped_by_similarity_dedupe": similarity_drops,
        "dropped_no_date": dropped_no_date,
        "dropped_out_of_window": dropped_out_of_window,
        "source_errors": source_errors,
    }
    return deduped, pipeline_summary, len(all_articles)


def get_headlines(ticker: yf.Ticker, symbol: str) -> tuple[list[str], str]:
    """Compatibility wrapper returning plain headline strings and the winning source."""
    limit = get_settings().max_news_items
    try:
        info: Any = ticker.info
        company_name = info.get("shortName", "") if isinstance(info, dict) else ""
    except (OSError, TimeoutError, ValueError) as exc:
        logger.warning("Company metadata request failed: %s", type(exc).__name__)
        company_name = ""

    articles, _, _ = fetch_articles_for_symbol(symbol, company_name)
    titles = [sanitize_markdown(article.title) for article in articles[:limit]]
    source = ",".join(sorted({_source_label(article.source) for article in articles[:limit]}))
    if source:
        return titles, source
    return titles, "none"
