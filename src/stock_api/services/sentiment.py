"""FinBERT sentiment scoring utilities."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from ..services.news import Article, sanitize_markdown

Classifier = Callable[..., Any]


def load_classifier(model_name: str | None = None) -> Classifier:
    """Load the configured FinBERT text-classification pipeline."""
    from transformers import pipeline

    return pipeline(
        "text-classification", model=model_name or get_settings().finbert_model_name, top_k=None
    )


def score_headlines(headlines: Sequence[str], classifier: Classifier) -> float | None:
    """Return mean positive-minus-negative probability for headlines."""
    if not headlines:
        return None
    results = classifier(list(headlines), truncation=True)
    scores: list[float] = []
    for result in results:
        probability_map: dict[str, float] = {}
        for item in result:
            label = str(item.get("label", "")).lower()
            probability_map[label] = float(item.get("score", 0.0))
        scores.append(probability_map.get("positive", 0.0) - probability_map.get("negative", 0.0))
    return sum(scores) / len(scores) if scores else None


def _article_time_weight(article: Article) -> float:
    settings = get_settings()
    published = article.published_at
    if published is None:
        return 0.1
    age_days = (datetime.now(timezone.utc) - published).total_seconds() / 86400
    return 0.5 ** (max(age_days, 0.0) / max(settings.half_life_days, 0.1))


def _infer_article_class(score: float, threshold: float | None = None) -> str:
    boundary = get_settings().article_pos_threshold if threshold is None else threshold
    if score > boundary:
        return "positive"
    if score < -boundary:
        return "negative"
    return "neutral"


def aggregate_sentiment(
    articles: Sequence[Article], classifier: Classifier, *, min_articles: int | None = None
) -> dict[str, Any]:
    """Aggregate weighted article scores into the public sentiment payload."""
    settings = get_settings()
    limit = settings.min_articles_for_label if min_articles is None else min_articles
    if not articles:
        return {
            "sentiment_label": "tidak ada data",
            "sentiment_score": None,
            "positive_pct": 0.0,
            "neutral_pct": 0.0,
            "negative_pct": 0.0,
            "top_headlines": [],
            "news_count": 0,
            "articles_scored": 0,
        }

    texts = [f"{article.title}. {article.summary}".strip() for article in articles]
    raw_results = classifier(list(texts), truncation=True)
    weighted_scores: list[tuple[float, float, str, str]] = []
    for index, article in enumerate(articles):
        if index >= len(raw_results):
            break
        result = raw_results[index]
        if not isinstance(result, list):
            continue
        probability_map: dict[str, float] = {}
        for item in result:
            label = str(item.get("label", "")).lower()
            probability_map[label] = float(item.get("score", 0.0))
        score = probability_map.get("positive", 0.0) - probability_map.get("negative", 0.0)
        weight = _article_time_weight(article)
        label = _infer_article_class(score)
        weighted_scores.append((score, weight, label, sanitize_markdown(article.title)))

    if not weighted_scores:
        return {
            "sentiment_label": "tidak ada data",
            "sentiment_score": None,
            "positive_pct": 0.0,
            "neutral_pct": 0.0,
            "negative_pct": 0.0,
            "top_headlines": [],
            "news_count": 0,
            "articles_scored": 0,
        }

    total_weight = sum(weight for _, weight, _, _ in weighted_scores)
    weighted_mean = (
        sum(score * weight for score, weight, _, _ in weighted_scores) / total_weight
        if total_weight
        else 0.0
    )
    positive_pct = (
        sum(
            weight for _, weight, label, _ in weighted_scores if label == "positive"
        )
        / total_weight
        * 100
    )
    neutral_pct = (
        sum(weight for _, weight, label, _ in weighted_scores if label == "neutral")
        / total_weight
        * 100
    )
    negative_pct = (
        sum(weight for _, weight, label, _ in weighted_scores if label == "negative")
        / total_weight
        * 100
    )

    if len(weighted_scores) < limit:
        label = "data terbatas"
    elif weighted_mean > settings.label_threshold:
        label = "bagus"
    elif weighted_mean < -settings.label_threshold:
        label = "buruk"
    else:
        label = "netral"

    top_headlines = [
        title
        for _, _, _, title in sorted(
            weighted_scores, key=lambda item: abs(item[0]) * item[1], reverse=True
        )[:3]
    ]
    return {
        "sentiment_label": label,
        "sentiment_score": round(weighted_mean, 3),
        "positive_pct": round(float(positive_pct), 1),
        "neutral_pct": round(float(neutral_pct), 1),
        "negative_pct": round(float(negative_pct), 1),
        "top_headlines": top_headlines,
        "news_count": len(weighted_scores),
        "articles_scored": len(weighted_scores),
    }


def label_from_score(score: float | None, threshold: float | None = None) -> str:
    """Map a sentiment score to the existing Indonesian label contract."""
    boundary = get_settings().sentiment_threshold if threshold is None else threshold
    if score is None:
        return "tidak ada data"
    if score > boundary:
        return "bagus"
    if score < -boundary:
        return "buruk"
    return "netral"
