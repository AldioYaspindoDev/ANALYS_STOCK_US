"""Unit tests for news parsing and deduplication."""

from unittest.mock import Mock

from src.stock_api.services.news import (
    dedupe,
    headlines_from_google_news,
    headlines_from_yfinance,
)


def test_dedupe_is_case_insensitive_and_preserves_order() -> None:
    assert dedupe(["Headline", "headline", "Other"]) == ["Headline", "Other"]


def test_parses_both_yfinance_news_shapes() -> None:
    ticker = Mock()
    ticker.news = [
        {"title": "Legacy format"},
        {"content": {"title": "Nested format"}},
        {"content": {}},
    ]
    assert headlines_from_yfinance(ticker) == ["Legacy format", "Nested format"]


def test_parses_google_news_rss(monkeypatch) -> None:
    response = Mock()
    response.content = (
        b"<rss><channel><item><title>Seagate outlook improves - Example News</title>"
        b"</item></channel></rss>"
    )
    response.raise_for_status.return_value = None
    get = Mock(return_value=response)
    monkeypatch.setattr("src.stock_api.services.news.requests.get", get)

    assert headlines_from_google_news("Seagate stock") == ["Seagate outlook improves"]
    get.assert_called_once()
