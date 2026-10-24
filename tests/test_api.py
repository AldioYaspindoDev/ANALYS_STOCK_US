"""API tests with external dependencies mocked."""

from unittest.mock import Mock

import pandas as pd
from fastapi.testclient import TestClient

from src.stock_api.main import create_app


def _client(monkeypatch, *, empty_history: bool = False) -> TestClient:
    history = pd.DataFrame({"Close": [] if empty_history else [100.0, 110.0]})
    ticker = Mock()
    ticker.history.return_value = history
    ticker.news = [{"title": "Company reports strong results"}]
    monkeypatch.setattr("src.stock_api.services.market.yf.Ticker", lambda symbol: ticker)
    monkeypatch.setattr("src.stock_api.services.stock.yf.Ticker", lambda symbol: ticker)
    classifier = Mock(
        return_value=[[{"label": "positive", "score": 0.8}, {"label": "negative", "score": 0.1}]]
    )
    return TestClient(create_app(classifier_loader=lambda: classifier))


def test_health_endpoint(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_info_contract_and_ticker_validation(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.get("/info/STX")
        dotted_ticker = client.get("/info/BRK-B")
        invalid = client.get("/info/TOO_LONG")
    assert response.status_code == 200
    assert list(response.json()) == [
        "ticker",
        "price",
        "change_pct",
        "sentiment_label",
        "sentiment_score",
        "news_count",
        "news_source",
        "top_headlines",
    ]
    assert response.json() == {
        "ticker": "STX",
        "price": 110.0,
        "change_pct": 10.0,
        "sentiment_label": "bagus",
        "sentiment_score": 0.7,
        "news_count": 1,
        "news_source": "yfinance",
        "top_headlines": ["Company reports strong results"],
    }
    assert invalid.status_code == 400
    assert dotted_ticker.status_code == 200
    assert dotted_ticker.json()["ticker"] == "BRK-B"


def test_info_returns_not_found_for_missing_market_data(monkeypatch) -> None:
    with _client(monkeypatch, empty_history=True) as client:
        response = client.get("/info/ZZZZZ")
    assert response.status_code == 404
