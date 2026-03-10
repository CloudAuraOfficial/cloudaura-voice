from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import StarletteHTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.logging_config import configure_logging
from app.models.schemas import ErrorResponse
from app.routers import health, webhooks

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info(
        "app.startup",
        environment=settings.environment,
        port=settings.app_port,
        livekit_url=settings.livekit_url,
    )
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CloudAura Voice Agent",
        description="AI personal agent for Ranjith — handles inbound recruiter calls",
        version="1.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(webhooks.router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing_page():
        return (STATIC_DIR / "index.html").read_text()

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return HTMLResponse(
                content=(STATIC_DIR / "404.html").read_text(),
                status_code=404,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        structlog.get_logger(__name__).error(
            "app.unhandled_exception",
            path=str(request.url),
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error="Internal server error").model_dump(),
        )

    return app


app = create_app()
