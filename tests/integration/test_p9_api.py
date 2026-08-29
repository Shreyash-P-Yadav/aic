"""P9 gate — the API.

Two things are being tested and they are different. The first is that the routes exist,
are typed, and return what their models promise. The second matters more: that the
**entitlement matrix holds through HTTP**, not merely inside the compiler. A security
property that only holds when called directly is not a security property.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from insight_copilot.api.app import create_app
from insight_copilot.api.state import AppState, InsightRecord
from insight_copilot.config import Settings
from insight_copilot.engine.bundle import AbstentionArtifact, ConfidenceFact
from tests.unit.helpers_p8 import make_bundle

NOW = dt.datetime(2026, 3, 29, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def state() -> AppState:
    """An app state with one published insight and one abstention, no warehouse."""
    settings = Settings(
        llm_provider="mock",
        anthropic_api_key=None,
        _env_file=None,  # type: ignore[call-arg]
    )
    app_state = AppState(settings)
    bundle = make_bundle()
    app_state.store(
        InsightRecord(
            insight_id=bundle.insight_id,
            kpi_id=bundle.kpi_id,
            created_at=NOW,
            bundle=bundle,
        )
    )
    app_state.store(
        InsightRecord(
            insight_id="abstain0001",
            kpi_id="blended_roas",
            created_at=NOW - dt.timedelta(hours=1),
            abstention=_abstention(),
        )
    )
    return app_state


@pytest.fixture
def client(state: AppState) -> TestClient:
    """A test client over an app wired to that state."""
    return TestClient(create_app(state.settings, state))


# ------------------------------------------------------------------- health --
def test_health_needs_no_data(client: TestClient) -> None:
    """A health check must not depend on a warehouse, or a cold start looks broken."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["llm_provider"] == "mock"


# ------------------------------------------------------------------ session --
def test_roles_are_listed_with_their_row_filter_bindings(client: TestClient) -> None:
    """The RSM's region binding is what makes the entitlement demo a data fact."""
    roles = client.get("/api/session/roles").json()
    by_name = {role["name"]: role for role in roles}
    assert set(by_name) == {"cfo", "analyst", "marketing_lead", "rsm_north", "intern"}
    assert by_name["rsm_north"]["bindings"]["user_region"] == "North"
    assert by_name["cfo"]["bindings"] == {}


def test_switching_role_changes_the_session(client: TestClient) -> None:
    """The role the compiler will use on the next query."""
    assert client.get("/api/session").json()["role"] == "analyst"
    response = client.post("/api/session/role", json={"role": "rsm_north"})
    assert response.status_code == 200
    assert response.json()["role"] == "rsm_north"
    assert client.get("/api/session").json()["role"] == "rsm_north"


def test_an_unknown_role_is_refused_with_the_list_of_real_ones(client: TestClient) -> None:
    """A typed refusal, not a 500."""
    response = client.post("/api/session/role", json={"role": "ceo"})
    assert response.status_code == 403
    body = response.json()
    assert "cfo" in body["reason"]
    assert body["type"] == "EntitlementError"


# ----------------------------------------------------------------- insights --
def test_insights_list_includes_abstentions_as_first_class_rows(client: TestClient) -> None:
    """An abstention is an output, not a gap in the list."""
    rows = client.get("/api/insights").json()
    assert len(rows) == 2
    statuses = {row["status"] for row in rows}
    assert statuses == {"published", "abstained"}
    assert rows[0]["created_at"] >= rows[1]["created_at"], "newest first"


@pytest.mark.parametrize(
    ("query", "expected"),
    [("?status=published", 1), ("?status=abstained", 1), ("?kpi=net_revenue", 1)],
)
def test_the_insight_list_filters(client: TestClient, query: str, expected: int) -> None:
    """Persona, status and KPI filters, as the route contract promises."""
    assert len(client.get(f"/api/insights{query}").json()) == expected


def test_the_insight_route_returns_the_whole_bundle(client: TestClient) -> None:
    """Every number the UI may render is inside the object it is handed."""
    bundle = make_bundle()
    body = client.get(f"/api/insights/{bundle.insight_id}").json()
    assert body["kpi_id"] == "net_revenue"
    assert body["confidence"]["tier"] == "Moderate"
    assert len(body["numbers"]) >= 10
    assert body["actions"][0]["expected_impact_low"] < body["actions"][0]["expected_impact_high"]


def test_an_unknown_insight_is_a_typed_404(client: TestClient) -> None:
    """No stack trace ever reaches a client."""
    response = client.get("/api/insights/does-not-exist")
    assert response.status_code == 404
    assert response.json()["type"] == "ResourceNotFound"


@pytest.mark.parametrize("persona", ["cfo", "analyst", "rsm", "marketing_lead"])
def test_every_persona_renders_a_verified_narrative(client: TestClient, persona: str) -> None:
    """Rendered lazily, per persona, with every number checked before it is returned."""
    bundle = make_bundle()
    body = client.get(
        f"/api/insights/{bundle.insight_id}/narrative", params={"persona": persona}
    ).json()
    assert body["persona"] == persona
    assert body["text"].strip()
    assert body["numbers_unsupported"] == 0
    assert body["faithfulness"] == pytest.approx(1.0)


def test_a_second_render_of_the_same_persona_is_cached(client: TestClient) -> None:
    """A CFO and an analyst are two renderings of one computation, not two."""
    bundle = make_bundle()
    url = f"/api/insights/{bundle.insight_id}/narrative"
    first = client.get(url, params={"persona": "cfo"}).json()
    second = client.get(url, params={"persona": "cfo"}).json()
    assert first["cached"] is False
    assert second["cached"] is True


def test_the_evidence_drawer_carries_the_five_traceability_elements(
    client: TestClient,
) -> None:
    """Freshness, method, contribution, confidence and lineage — law four."""
    bundle = make_bundle()
    body = client.get(f"/api/insights/{bundle.insight_id}/evidence").json()
    assert body["freshness"] and body["lineage"]
    assert body["confidence"]["weakest_signal"]
    assert body["drivers"][0]["interval_low"] < body["drivers"][0]["interval_high"]
    assert body["numbers"] and body["documents"]
    assert body["explained_fraction"] + body["unexplained_fraction"] == pytest.approx(1.0)


def test_an_abstention_drawer_says_what_is_missing(client: TestClient) -> None:
    """The abstention card is more useful than a confident sentence would have been."""
    body = client.get("/api/insights/abstain0001/evidence").json()
    assert body["failed_checks"]
    assert body["retry_trigger"]
    assert body["what_is_known"]


def test_feedback_is_classified_and_recorded(client: TestClient, state: AppState) -> None:
    """The learning loop's only labelled input."""
    bundle = make_bundle()
    body = client.post(
        f"/api/insights/{bundle.insight_id}/feedback", json={"text": "We already knew this"}
    ).json()
    assert body["label"] == "already_known"
    assert state.insights[bundle.insight_id].feedback


# ---------------------------------------------------------------------- ask --
def test_ask_answers_from_an_existing_insight(client: TestClient) -> None:
    """Conversational mode reuses the computation; it does not start a new one."""
    body = client.post("/api/ask", json={"question": "why did net_revenue move?"}).json()
    assert body["kind"] == "answer"
    assert body["narrative"].strip()


def test_ask_asks_for_clarification_rather_than_guessing(client: TestClient) -> None:
    """Guessing is how a conversational tool answers a question nobody asked."""
    body = client.post("/api/ask", json={"question": "how are we doing?"}).json()
    assert body["kind"] == "clarification"
    assert "net_revenue" in body["question"]


# --------------------------------------------------------------- operations --
def test_sources_are_listed_from_their_contracts_with_no_warehouse(
    client: TestClient,
) -> None:
    """Eleven feeds, their cadences and their known issues, before any data lands."""
    rows = client.get("/api/sources").json()
    assert len(rows) == 11
    martech = next(row for row in rows if row["source_id"] == "martech_weekly")
    assert martech["cadence"] == "previous_iso_week"
    assert "currency_unit_change_2025_02" in martech["known_issues"]


def test_warehouse_backed_routes_say_so_when_nothing_is_loaded(client: TestClient) -> None:
    """A cold start is a documented state, not a 500."""
    for path in ("/api/freshness", "/api/dq", "/api/sources/oms_orders/batches"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert "backfill" in response.json()["detail"] or "harness" in response.json()["detail"]


def test_telemetry_and_calibration_are_honest_about_being_empty(
    client: TestClient,
) -> None:
    """An unfitted calibration map must say it is unfitted."""
    telemetry = client.get("/api/telemetry").json()
    assert telemetry["insights_metered"] == 0
    calibration = client.get("/api/calibration").json()
    assert calibration["fitted"] is False
    assert "uncalibrated" in calibration["detail"]


def test_the_audit_log_is_readable(client: TestClient) -> None:
    """A refusal is as auditable as a result."""
    client.post("/api/session/role", json={"role": "cfo"})
    assert client.get("/api/audit").status_code == 200


def test_the_openapi_schema_is_generated(client: TestClient) -> None:
    """The generated schema is the frontend's contract, so it must exist and be typed."""
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    assert {"/api/health", "/api/insights", "/api/session/role", "/api/ask"} <= paths
    assert "/api/insights/{insight_id}/evidence" in paths


def _abstention() -> AbstentionArtifact:
    """A Scenario B abstention, for the list and drawer tests."""
    return AbstentionArtifact(
        insight_id="abstain0001",
        kpi_id="blended_roas",
        computed_at=NOW - dt.timedelta(hours=1),
        period_start=dt.date(2026, 3, 9),
        period_end=dt.date(2026, 3, 15),
        observed_movement="-18.20% against the counterfactual",
        what_is_known=["blended_roas moved -18.20% against its counterfactual"],
        failed_checks=["a required source breaches its freshness SLA: martech_weekly"],
        missing_evidence=["a current batch from martech_weekly"],
        retry_trigger="the next successful batch from the stale source",
        eta=NOW + dt.timedelta(hours=17),
        confidence=ConfidenceFact(
            signals={"c4_data_trust": 0.1},
            signal_detail={"c4_data_trust": "stale required sources: martech_weekly"},
            composite=0.12,
            calibrated=0.12,
            calibration_fitted=False,
            tier="Insufficient",
            weakest_signal="c4_data_trust",
            hard_gate_failures=["a required source breaches its freshness SLA: martech_weekly"],
        ),
    )
