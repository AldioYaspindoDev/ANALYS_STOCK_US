"""HTTP endpoints for health and ticker information."""

from fastapi import APIRouter, HTTPException, Request

from ..schemas import HealthResponse, StockInfoResponse
from ..services.market import MarketDataNotFoundError
from ..services.stock import InvalidTickerError

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return the API liveness status."""
    return HealthResponse(status="ok")


@router.get("/info/{ticker}", response_model=StockInfoResponse)
def info(ticker: str, request: Request) -> StockInfoResponse:
    """Return current market data and headline sentiment for a ticker."""
    try:
        payload = request.app.state.stock_service.get_info(ticker)
    except InvalidTickerError as exc:
        raise HTTPException(status_code=400, detail="Ticker tidak valid") from exc
    except MarketDataNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"Data {ticker.upper()} tidak ditemukan"
        ) from exc
    return StockInfoResponse(**payload)
