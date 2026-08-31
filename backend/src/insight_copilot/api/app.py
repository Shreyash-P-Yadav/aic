"""FastAPI application factory.

WHY a factory rather than a module-level ``app``: tests construct an app with
injected settings, and a factory keeps that from mutating process state.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from insight_copilot import __version__
from insight_copilot.api.errors import install_exception_handlers
from insight_copilot.api.routers import ask, health, insights, operations, session
from insight_copilot.api.state import AppState
from insight_copilot.config import Settings, get_settings
from insight_copilot.logging import configure_logging, get_logger

logger = get_logger(__name__)


def create_app(settings: Settings | None = None, state: AppState | None = None) -> FastAPI:
    """Build the ASGI application with all routers and handlers installed."""
    cfg = settings or get_settings()
    configure_logging(cfg)

    app = FastAPI(
        title=cfg.app_name,
        version=__version__,
        description=(
            "KPI intelligence-to-action engine. Statistics decide; the model narrates. "
            "All data is simulated."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)
    # One shared state, constructed here and injected everywhere. Nothing expensive is
    # built: the warehouse and the harness are attached later, by the CLI or the demo,
    # so the app starts in milliseconds and a health check needs no data.
    app.state.copilot = state or AppState(cfg)
    for module in (health, session, insights, operations, ask):
        app.include_router(module.router)
    logger.info("api.created", environment=cfg.environment, llm_provider=cfg.llm_provider)
    return app


app = create_app()
