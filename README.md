# Stock Pipeline API

FastAPI service that returns recent market prices and FinBERT sentiment from recent headlines. The JSON response contract is `ticker`, `price`, `change_pct`, `sentiment_label`, `sentiment_score`, `news_count`, `news_source`, and `top_headlines`.

## Setup (Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

The FinBERT model is downloaded by Transformers when the API starts for the first time; ensure network access and enough memory/disk space.

## Run

```bash
uvicorn src.stock_api.main:app --reload --host 0.0.0.0
```

OpenAPI documentation is available at `http://localhost:8000/docs`. The blocking model initialization runs once during startup, so the first boot takes longer and fails fast if the model cannot load; this avoids a slow first ticker request. The classifier remains in memory for the process lifetime.

## Test

```bash
pytest
ruff check .
ruff format --check .
```

All test dependencies are mocked; tests do not make external requests or download a model.

## Example `/info/STX`

```json
{
  "ticker": "STX",
  "price": 100.0,
  "change_pct": 1.25,
  "sentiment_label": "bagus",
  "sentiment_score": 0.42,
  "news_count": 2,
  "news_source": "yfinance",
  "top_headlines": ["Example headline"]
}
```

Prices and headlines are indicative only. yfinance and Google News are not official market data sources.
