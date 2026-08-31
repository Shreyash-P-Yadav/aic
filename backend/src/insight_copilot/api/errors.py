"""Exception handlers that turn typed errors into typed problem responses."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from insight_copilot.api.schemas import ProblemDetail
from insight_copilot.errors import (
    ContractError,
    DataQualityError,
    EntitlementError,
    InsightCopilotError,
    InsufficientEvidenceError,
    LLMError,
    ResourceNotFound,
    ServiceUnavailable,
)
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

_STATUS_BY_TYPE: dict[type[InsightCopilotError], int] = {
    EntitlementError: 403,
    ResourceNotFound: 404,
    ServiceUnavailable: 503,
    ContractError: 422,
    DataQualityError: 409,
    InsufficientEvidenceError: 200,
    LLMError: 503,
}


def _status_for(exc: InsightCopilotError) -> int:
    """Most specific registered base class wins; unknown errors are 500."""
    for exc_type, status in _STATUS_BY_TYPE.items():
        if isinstance(exc, exc_type):
            return status
    return 500


def install_exception_handlers(app: FastAPI) -> None:
    """Register the single handler for our exception hierarchy."""

    @app.exception_handler(InsightCopilotError)
    async def _handle(request: Request, exc: InsightCopilotError) -> JSONResponse:
        status = _status_for(exc)
        reason = getattr(exc, "reason", None)
        logger.warning(
            "api.error",
            error_type=type(exc).__name__,
            status=status,
            path=request.url.path,
            message=exc.message,
        )
        problem = ProblemDetail(
            type=type(exc).__name__,
            title=exc.message,
            status=status,
            detail=exc.detail,
            reason=reason,
            instance=request.url.path,
        )
        return JSONResponse(status_code=status, content=problem.model_dump())
