"""FinBERT sentiment scoring utilities."""

from collections.abc import Callable, Sequence
from typing import Any

from ..config import get_settings

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
        probabilities = {item["label"].lower(): float(item["score"]) for item in result}
        scores.append(probabilities.get("positive", 0.0) - probabilities.get("negative", 0.0))
    return sum(scores) / len(scores) if scores else None


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
