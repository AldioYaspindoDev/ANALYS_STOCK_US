"""Unit tests for sentiment labels and scores."""

from src.stock_api.services.sentiment import label_from_score, score_headlines


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
