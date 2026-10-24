"""Unit tests for sentiment labels and scores."""

from src.stock_api.services.news import Article, sanitize_markdown
from src.stock_api.services.sentiment import aggregate_sentiment, label_from_score, score_headlines


def test_label_from_score_boundaries_and_none() -> None:
    assert label_from_score(None) == "tidak ada data"
    assert label_from_score(0.151) == "bagus"
    assert label_from_score(0.15) == "netral"
    assert label_from_score(-0.15) == "netral"
    assert label_from_score(-0.151) == "buruk"


def test_score_headlines_averages_positive_minus_negative() -> None:
    def classifier(texts: list[str], **kwargs: object) -> list[list[dict[str, str | float]]]:
        return [
            [{"label": "positive", "score": 0.8}, {"label": "negative", "score": 0.1}],
            [{"label": "positive", "score": 0.2}, {"label": "negative", "score": 0.4}],
        ]

    assert score_headlines(["first", "second"], classifier) == 0.25
    assert score_headlines([], classifier) is None


def test_aggregate_sentiment_and_markdown_cleanup() -> None:
    articles = [
        Article(
            title="Apple* [earnings] _guidance_ `beat`",
            summary="Strong quarter and guidance.",
            source="finnhub",
            publisher="Business Wire",
            url="https://example.com/1",
            published_at=None,
        ),
        Article(
            title="Apple outlook weakens",
            summary="Sales outlook softened.",
            source="googlenews",
            publisher="CNBC",
            url="https://example.com/2",
            published_at=None,
        ),
    ]

    result = aggregate_sentiment(articles, classifier=lambda texts, **kwargs: [
        [{"label": "positive", "score": 0.9}, {"label": "negative", "score": 0.05}],
        [{"label": "positive", "score": 0.1}, {"label": "negative", "score": 0.8}],
    ])

    assert result["sentiment_label"] in {
        "bagus",
        "netral",
        "buruk",
        "data terbatas",
        "tidak ada data",
    }
    assert result["news_count"] == 2
    assert sanitize_markdown("Apple* [earnings] _guidance_ `beat`") == (
        "Apple (earnings) guidance beat"
    )
    assert result["top_headlines"][0].startswith("Apple")
