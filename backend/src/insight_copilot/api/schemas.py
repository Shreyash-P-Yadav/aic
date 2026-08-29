"""Shared API response models.

WHY pydantic at the boundary: the build standard forbids dicts crossing module
boundaries. The generated OpenAPI schema is then also the frontend's contract, so a
renamed field breaks the TypeScript build rather than a demo.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: Literal["ok"] = "ok"
    version: str
    llm_provider: str
    environment: str


class ProblemDetail(BaseModel):
    """RFC-7807-shaped error body.

    WHY: errors must never return a stack trace. The ``type`` field is the exception
    class name so a client can branch on it, and ``reason`` carries policy text
    verbatim for entitlement denials.
    """

    type: str
    title: str
    status: int
    detail: str | None = None
    reason: str | None = None
    instance: str | None = Field(default=None, description="run_id or request path")
