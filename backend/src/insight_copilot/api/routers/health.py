"""Liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from insight_copilot import __version__
from insight_copilot.api.schemas import HealthResponse
from insight_copilot.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report liveness plus the two facts a demo operator needs at a glance."""
    return HealthResponse(
        version=__version__,
        llm_provider=settings.llm_provider,
        environment=settings.environment,
    )
