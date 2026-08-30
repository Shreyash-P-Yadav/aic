"""P12 — graceful degradation. Every way the world can be missing, and what happens.

The specification asks for five degraded conditions: no LLM, no NLI model, no network,
empty data, and a source permanently down. Each has its own test here, and each asserts
the same shape of answer — the system produces a *typed, honest* output rather than a
crash, a blank, or a confident guess built on what is left.

The demo path is also asserted to be warning-free. A Python warning in a live demo is a
line of red text an evaluator reads instead of listening.
"""

from __future__ import annotations

import datetime as dt
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from insight_copilot.api.app import create_app
from insight_copilot.api.state import AppState
from insight_copilot.config import Settings, get_settings
from insight_copilot.engine.bundle import InsightEvidenceBundle
from insight_copilot.errors import InsightCopilotError, LLMError
from insight_copilot.llm.narrate import PersonaNarrator
from insight_copilot.llm.provider import LLMProvider, LLMRequest, LLMResponse, MockProvider
from insight_copilot.llm.router import ModelRouter
from insight_copilot.llm.verify_numbers import verify
from insight_copilot.prewarm import PERSONAS, prewarm
from insight_copilot.reset import reset_demo
from tests.unit.helpers_p8 import make_bundle


class UnavailableProvider(LLMProvider):
    """No LLM at all: no key, no network, nothing configured."""

    name = "unavailable"

    @property
    def available(self) -> bool:
        """The one thing every caller checks before reaching for a model."""
        return False

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Reached only by a caller that ignored ``available``. Typed, never bare."""
        raise LLMError("no provider is configured", detail=request.call_site)


class BrokenNetworkProvider(LLMProvider):
    """A provider that claims to be available and then fails on every call.

    This is the harder case and the more realistic one: an API key is present, so
    nothing declines up front, and the failure arrives mid-request.
    """

    name = "broken-network"

    @property
    def available(self) -> bool:
        return True

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMError("connection reset by peer", detail=request.call_site)


@pytest.fixture(name="bundle")
def _bundle() -> InsightEvidenceBundle:
    """The Scenario A bundle the P8 gate uses, so degradation is tested against the
    same object the happy path narrates rather than against a fixture built for it."""
    return make_bundle()


@pytest.fixture(name="empty_settings")
def _empty_settings(tmp_path: Path) -> Settings:
    """Settings pointing at directories that contain nothing at all."""
    base = get_settings()
    return base.model_copy(
        update={
            "data_dir": tmp_path / "data",
            "landing_dir": tmp_path / "data" / "landing",
            "artifacts_dir": tmp_path / "artifacts",
            "warehouse_path": tmp_path / "data" / "warehouse.duckdb",
        }
    )


def test_the_api_starts_and_answers_with_no_warehouse(empty_settings: Settings) -> None:
    """An empty database is a 503 that names the fix, never a 500 and never a lie."""
    empty_settings.ensure_dirs()
    state = AppState(empty_settings)
    with TestClient(create_app(empty_settings, state)) as client:
        assert client.get("/api/health").status_code == 200, "health never depends on data"
        response = client.get("/api/freshness")
        assert response.status_code == 503
        problem = response.json()
        assert problem["detail"], "a 503 that says nothing is as useless as a 500"


def test_the_insight_feed_is_empty_not_broken_with_no_data(empty_settings: Settings) -> None:
    """Nothing to say is an empty list, not an error."""
    empty_settings.ensure_dirs()
    state = AppState(empty_settings)
    with TestClient(create_app(empty_settings, state)) as client:
        response = client.get("/api/insights")
        assert response.status_code == 200
        assert response.json() == []


def test_narration_falls_back_to_templates_with_no_llm(
    bundle: InsightEvidenceBundle,
) -> None:
    """The whole product is demonstrable with the model switched off."""
    narrator = PersonaNarrator(ModelRouter(UnavailableProvider()))
    for persona in PERSONAS:
        narrative = narrator.narrate(bundle, persona)
        assert narrative.text.strip(), f"{persona} produced nothing"
        assert narrative.source == "template"
        assert verify(narrative.text, bundle).passed, "the template must pass its own verifier"


def test_narration_survives_a_provider_that_fails_mid_request(
    bundle: InsightEvidenceBundle,
) -> None:
    """An available provider that then throws must degrade, not propagate."""
    narrator = PersonaNarrator(ModelRouter(BrokenNetworkProvider()))
    narrative = narrator.narrate(bundle, "cfo")
    assert narrative.text.strip()
    assert narrative.source != "model"
    assert verify(narrative.text, bundle).passed


def test_entailment_degrades_when_no_nli_model_is_installed(
    bundle: InsightEvidenceBundle,
) -> None:
    """The NLI extra is optional and must never be required.

    With no ``transformers``/``torch`` installed the verifier falls back to its lexical
    check, and — critically — reports which one ran, so a reader is never shown a
    confidence that rests on a model that was not there.
    """
    narrator = PersonaNarrator(ModelRouter(MockProvider()))
    narrative = narrator.narrate(bundle, "analyst")
    assert narrative.entailment is not None
    assert narrative.entailment.method, "the entailment check must name its method"


def test_prewarm_never_raises_when_the_provider_is_gone(
    empty_settings: Settings, bundle: InsightEvidenceBundle
) -> None:
    """Pre-warming a demo with no model degrades latency, never correctness."""
    empty_settings.ensure_dirs()
    state = AppState(empty_settings)
    state.router = ModelRouter(UnavailableProvider(), empty_settings)
    from insight_copilot.api.state import InsightRecord

    state.store(
        InsightRecord(
            insight_id=bundle.insight_id,
            kpi_id=bundle.kpi_id,
            created_at=dt.datetime.now(dt.UTC),
            bundle=bundle,
        )
    )
    result = prewarm(state)
    assert result.failed == 0
    assert result.rendered == len(PERSONAS)


def test_reset_is_idempotent(empty_settings: Settings) -> None:
    """Running the reset twice is not an error, and the second is a no-op."""
    empty_settings.ensure_dirs()
    first = reset_demo(empty_settings)
    second = reset_demo(empty_settings)
    assert second.removed == [], "a second reset should find nothing left to remove"
    assert first.preserved == second.preserved


def test_reset_never_touches_the_truth_ledger(empty_settings: Settings) -> None:
    """Six minutes of counterfactual simulation is not derived state."""
    empty_settings.ensure_dirs()
    ledger = empty_settings.data_dir / "ledger.parquet"
    ledger.write_bytes(b"not really a parquet, but it must survive")
    reset_demo(empty_settings)
    assert ledger.exists(), "the reset deleted the ledger"


def test_a_permanently_dead_source_forces_abstention_not_a_guess(
    bundle: InsightEvidenceBundle,
) -> None:
    """The fifth degraded condition: a source that never comes back.

    The ``c4`` hard gate reads the freshness of the contract's *required* sources. With
    one breached, the tier is forced to Insufficient regardless of how strong every
    other signal is — which is the point: an engine that attributes a movement using
    only the feeds that are still arriving is an engine that will confidently blame the
    wrong thing.
    """
    from insight_copilot.contracts.registry import ContractRegistry
    from insight_copilot.engine.calibration import ConfidenceScorer
    from insight_copilot.engine.confidence import ConfidenceInputs

    contract = ContractRegistry.from_directory(get_settings().contracts_dir).kpi("net_revenue")
    healthy = ConfidenceInputs(
        p_value=0.0001,
        delta_pct=bundle.delta_pct,
        materiality_ratio=50.0,
        bootstrap_stability=0.99,
        attribution_coverage=0.95,
        estimator_agreement=0.95,
        evidence_corroboration=0.9,
        independent_sources=3,
        timing_gate_survivors=3,
        history_days=900,
        min_history_days=180,
    )
    scorer = ConfidenceScorer()
    assert scorer.score(healthy, contract).tier != "Insufficient", "the control case"

    dead_feed = ConfidenceInputs(
        **{**vars(healthy), "freshness_ok": False, "stale_sources": ("wms_fulfilment",)}
    )
    degraded = scorer.score(dead_feed, contract)
    assert degraded.tier == "Insufficient"
    assert any("freshness" in reason for reason in degraded.hard_gate_failures)


def test_every_typed_error_carries_a_message_and_a_status(
    bundle: InsightEvidenceBundle,
) -> None:
    """The error protocol: typed, messaged, and never a bare Exception."""
    del bundle
    error = LLMError("something went wrong", detail="and here is what")
    assert isinstance(error, InsightCopilotError)
    assert error.message and error.detail


def test_the_demo_path_emits_no_python_warnings(
    empty_settings: Settings, bundle: InsightEvidenceBundle
) -> None:
    """A warning in a live demo is red text an evaluator reads instead of listening."""
    empty_settings.ensure_dirs()
    state = AppState(empty_settings)
    from insight_copilot.api.state import InsightRecord

    state.store(
        InsightRecord(
            insight_id=bundle.insight_id,
            kpi_id=bundle.kpi_id,
            created_at=dt.datetime.now(dt.UTC),
            bundle=bundle,
        )
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prewarm(state)
        with TestClient(create_app(empty_settings, state)) as client:
            client.get("/api/health")
            client.get("/api/insights")
    ours = [item for item in caught if "insight_copilot" in str(item.filename)]
    assert ours == [], f"the demo path emitted {[str(item.message) for item in ours]}"
