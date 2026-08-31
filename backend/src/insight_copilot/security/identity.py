"""Identities, roles and the session context every query is compiled against.

WHY the session carries *bound values* rather than a pre-built filter string: the
contract owns the filter template (``region = :user_region``); the session owns the
value (``North``). Keeping them apart is what makes the value a bind parameter and
therefore unable to change the shape of the query, whatever it contains.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RoleName = Literal["cfo", "rsm_north", "analyst", "marketing_lead", "intern"]

ROLE_NAMES: tuple[RoleName, ...] = ("cfo", "rsm_north", "analyst", "marketing_lead", "intern")

_ALLOWED_BINDINGS: frozenset[str] = frozenset({"user_region", "user_warehouse", "user_channel"})
"""The only session attributes a contract row filter may reference.

WHY an allowlist rather than "whatever the session has": a contract is a governance
artefact edited by a human, and a typo (``:user_regionn``) must fail loudly at
compile time rather than silently bind NULL and return every row.
"""


class Role(BaseModel):
    """A named role and the session bindings it supplies to row filters."""

    model_config = ConfigDict(frozen=True)

    name: RoleName
    display_name: str
    description: str
    bindings: dict[str, str] = Field(default_factory=dict)

    @field_validator("bindings")
    @classmethod
    def _known_bindings(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - _ALLOWED_BINDINGS
        if unknown:
            raise ValueError(f"unknown session bindings: {sorted(unknown)}")
        return value


class Identity(BaseModel):
    """Who is asking. One person, one role, in this prototype."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    display_name: str
    role: Role


class SessionContext(BaseModel):
    """One request's security context, carried into every compile and audit row."""

    model_config = ConfigDict(frozen=True)

    identity: Identity
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    intent: str = Field(default="proactive_scan", description="Audited free-text intent label.")

    @property
    def role_name(self) -> RoleName:
        """Shorthand used to look up the contract's policy for this caller."""
        return self.identity.role.name

    @property
    def bindings(self) -> dict[str, str]:
        """Session values available to a contract row-filter template."""
        return dict(self.identity.role.bindings)


# The five prototype roles. National scope unless stated; the RSM is region-bound,
# which is what makes the entitlement demo a data fact rather than a UI toggle.
ROLES: dict[RoleName, Role] = {
    "cfo": Role(
        name="cfo",
        display_name="CFO",
        description="Board-ready impact view. Full national scope, no masks.",
    ),
    "analyst": Role(
        name="analyst",
        display_name="Analyst",
        description="Full method access: coefficients, diagnostics, lineage, residuals.",
    ),
    "marketing_lead": Role(
        name="marketing_lead",
        display_name="Marketing Lead",
        description="Full marketing domain; margin columns masked.",
    ),
    "rsm_north": Role(
        name="rsm_north",
        display_name="Regional Sales Manager — North",
        description="Region-scoped rows; margin and discount columns masked; no marketing domain.",
        bindings={"user_region": "North", "user_warehouse": "DC-North"},
    ),
    "intern": Role(
        name="intern",
        display_name="Intern",
        description="Denied on financial and marketing KPIs; aggregate operational views only.",
    ),
}


def get_role(name: str) -> Role:
    """Look up a role, or fail with the list of valid names."""
    try:
        return ROLES[name]  # type: ignore[index]  # narrowed by the KeyError below
    except KeyError as exc:
        raise ValueError(f"unknown role {name!r}; known: {', '.join(ROLE_NAMES)}") from exc


def session_for(
    role_name: str, *, user_id: str | None = None, intent: str = "proactive_scan"
) -> SessionContext:
    """Build a session for a role. Convenience for the API, the CLI and tests."""
    role = get_role(role_name)
    return SessionContext(
        identity=Identity(
            user_id=user_id or f"{role.name}@meridian.example.com",
            display_name=role.display_name,
            role=role,
        ),
        intent=intent,
    )
