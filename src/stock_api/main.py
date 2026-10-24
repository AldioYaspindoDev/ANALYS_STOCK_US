"""FastAPI application factory and application lifespan."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from .config import get_settings
from .routers.info import router
from .services.sentiment import load_classifier
from .services.stock import StockInfoService


def create_app(classifier_loader: Callable[[], Any] | None = None) -> FastAPI:
    """Create the API application with a lifespan-owned classifier."""
    loader = classifier_loader or load_classifier

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.stock_service = StockInfoService(
            classifier=loader(),
            ttl_seconds=get_settings().cache_ttl_seconds,
        )
        yield
        del app.state.stock_service

    application = FastAPI(title="Stock Info API", lifespan=lifespan)
    application.include_router(router)
    return application


app = create_app()
