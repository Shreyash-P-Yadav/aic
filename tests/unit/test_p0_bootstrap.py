"""P0 gate: the scaffold is valid and the health endpoint answers.

These assertions are deliberately shallow — P0 builds no behaviour. Their job is to
prove the package imports, the settings model is coherent, the exception hierarchy is
wired to typed problem responses, and the API serves.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from insight_copilot import __version__
from insight_copilot.api.app import create_app
from insight_copilot.config import Settings
from insight_copilot.errors import (
    ContractError,
    EntitlementError,
    InsightCopilotError,
    InsufficientEvidenceError,
)


def test_health_returns_ok(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_mock_provider_is_the_default() -> None:
    """LLM_PROVIDER=mock must be the default so the suite runs with no API key."""
    assert Settings(_env_file=None).llm_provider == "mock"  # type: ignore[call-arg]


def test_openapi_schema_generates(settings: Settings) -> None:
    schema = create_app(settings).openapi()
    assert schema["info"]["version"] == __version__
    assert "/api/health" in schema["paths"]


def test_every_error_descends_from_the_root() -> None:
    for exc_type in (ContractError, EntitlementError, InsufficientEvidenceError):
        assert issubclass(exc_type, InsightCopilotError)


def test_entitlement_error_carries_its_policy_reason() -> None:
    """The denial reason is shown to the user verbatim, so it must survive the raise."""
    exc = EntitlementError(
        "denied",
        reason="Tier-1 financial KPI — request access from data_steward",
        contract_id="net_revenue",
        role="intern",
    )
    assert exc.reason.startswith("Tier-1 financial KPI")
    assert exc.contract_id == "net_revenue"
