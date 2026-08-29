"""Session and role. **Switching role switches the data, not the label.**

Row filters and column masks live in the contract compiler, below this API and below
the language model. A role change here changes what subsequent queries return, and an
attempt to read something the role is denied returns the contract's own policy text —
which is why the entitlement demo is a data fact rather than a UI toggle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from insight_copilot.api.deps import get_state
from insight_copilot.api.schemas import RoleRequest, RoleSummary, SessionResponse
from insight_copilot.api.state import AppState
from insight_copilot.errors import EntitlementError
from insight_copilot.security.identity import ROLES

router = APIRouter(tags=["session"])


@router.get("/api/session/roles", response_model=list[RoleSummary])
async def list_roles() -> list[RoleSummary]:
    """Every selectable role, with the bindings its row filters use."""
    return [
        RoleSummary(
            name=role.name,
            display_name=role.display_name,
            description=role.description,
            bindings=dict(role.bindings),
        )
        for _, role in sorted(ROLES.items())
    ]


@router.get("/api/session", response_model=SessionResponse)
async def current_session(state: AppState = Depends(get_state)) -> SessionResponse:
    """Who the API currently believes it is talking to."""
    return _describe(state)


@router.post("/api/session/role", response_model=SessionResponse)
async def set_role(payload: RoleRequest, state: AppState = Depends(get_state)) -> SessionResponse:
    """Switch role, or refuse with the list of roles that exist."""
    if payload.role not in ROLES:
        raise EntitlementError(
            f"unknown role {payload.role!r}",
            reason=f"Known roles: {', '.join(sorted(ROLES))}.",
            contract_id="session",
            role=payload.role,
        )
    state.set_role(payload.role)
    return _describe(state)


def _describe(state: AppState) -> SessionResponse:
    return SessionResponse(
        user_id=state.session.identity.user_id,
        role=state.session.role_name,
        display_name=state.session.identity.display_name,
        run_id=state.session.run_id,
    )
