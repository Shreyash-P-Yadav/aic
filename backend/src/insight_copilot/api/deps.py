"""Dependency wiring for the routes. One shared state, injected, never imported."""

from __future__ import annotations

from fastapi import Request

from insight_copilot.api.state import AppState


def get_state(request: Request) -> AppState:
    """The application state attached at startup. FastAPI injects the request."""
    state: AppState = request.app.state.copilot
    return state
