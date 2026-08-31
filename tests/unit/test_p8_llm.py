"""P8 gate — the LLM layer and the verifiers that make it safe.

The whole phase exists to make one sentence true: *an LLM may never produce, alter or
infer a numeric value.* Everything below tests the mechanism rather than the promise.
"""

from __future__ import annotations

import datetime as dt

import pytest

from insight_copilot.config import Settings
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.engine.bundle import (
    ActionFact,
    ConfidenceFact,
    InsightEvidenceBundle,
    NumberFact,
    SegmentFact,
)
from insight_copilot.errors import LLMError
from insight_copilot.llm.feedback import FeedbackClassifier
from insight_copilot.llm.hypotheses import HypothesisProposer
from insight_copilot.llm.narrate import PersonaNarrator
from insight_copilot.llm.planner import QueryPlanner
from insight_copilot.llm.provider import AnthropicProvider, MockProvider, build_provider
from insight_copilot.llm.router import ModelRouter
from insight_copilot.llm.templates import TemplateNarrator, format_amount, load_personas
from insight_copilot.llm.verify_entailment import cap_tier, causal_sentences
from insight_copilot.llm.verify_numbers import extract, verify
from insight_copilot.telemetry.meter import TelemetryLedger
from tests.unit.helpers_p8 import make_bundle, mock_settings


@pytest.fixture(scope="module")
def registry() -> ContractRegistry:
    """The shipped contracts."""
    from pathlib import Path

    import insight_copilot.contracts as package

    return ContractRegistry.from_directory(Path(package.__file__).resolve().parent)


@pytest.fixture
def bundle() -> InsightEvidenceBundle:
    """A realistic Scenario A bundle."""
    return make_bundle()


@pytest.fixture
def router() -> ModelRouter:
    """A router over the mock provider, at the shipped cost cap."""
    return ModelRouter(MockProvider(), mock_settings())


# ------------------------------------------------------------ mock end to end --
def test_mock_runs_the_whole_pipeline_offline_with_no_api_key(
    bundle: InsightEvidenceBundle, router: ModelRouter
) -> None:
    """**The hard requirement.** No key, no network, four personas, every one rendered."""
    narrator = PersonaNarrator(router)
    for persona in ("cfo", "analyst", "rsm", "marketing_lead"):
        narrative = narrator.narrate(bundle, persona)
        assert narrative.text.strip()
        assert narrative.persona == persona
        assert narrative.numbers is not None and narrative.numbers.passed


def test_build_provider_defaults_to_mock() -> None:
    """``LLM_PROVIDER=mock`` is the default and it is always available."""
    provider = build_provider(mock_settings())
    assert provider.name == "mock"
    assert provider.available is True


def test_every_persona_has_a_style_card() -> None:
    """Tone, length and permitted elements are governance, not prompt-craft."""
    cards = load_personas()
    assert set(cards) == {"cfo", "analyst", "rsm", "marketing_lead"}
    assert "coefficients" in cards["cfo"].forbidden_elements
    assert "coefficients" in cards["analyst"].required_elements
    for card in cards.values():
        assert set(card.tier_language) == {"High", "Moderate", "Low", "Insufficient"}


# --------------------------------------------------------------- verification --
def test_an_injected_wrong_number_is_caught_and_regenerated(
    bundle: InsightEvidenceBundle,
) -> None:
    """**The load-bearing test of the whole phase.**"""
    provider = MockProvider()
    provider.set_response(
        "narrate",
        "Net revenue fell 63.10% against its counterfactual, a shortfall of 99,999,999 rupees.",
    )
    narrator = PersonaNarrator(ModelRouter(provider, mock_settings()))
    narrative = narrator.narrate(bundle, "cfo")

    assert narrative.source == "template_after_failed_verification"
    assert narrative.attempts == 3, "the narrator must retry twice before falling back"
    assert narrative.rejected_drafts, "the rejected drafts are the audit trail"
    assert "63.10" not in narrative.text and "99,999,999" not in narrative.text
    assert narrative.numbers is not None and narrative.numbers.passed


def test_the_template_narrator_can_never_produce_an_unsupported_number(
    bundle: InsightEvidenceBundle,
) -> None:
    """It only interpolates facts, which is what makes it the safe floor."""
    narrator = TemplateNarrator()
    for persona in narrator.personas:
        result = verify(narrator.narrate(bundle, persona), bundle)
        assert result.passed, f"{persona}: {result.detail}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("down 11.94%", -11.94),
        ("down \u221211.94%", -11.94),  # U+2212, as spreadsheets emit it
        ("Rs 1.2 crore", 12_000_000.0),
        ("12.4 lakh", 1_240_000.0),
        ("10,000,000 rupees", 10_000_000.0),
        ("3.2pp lower", 3.2),
    ],
)
def test_indian_number_formats_are_all_extracted(text: str, expected: float) -> None:
    """A verifier that only understands 1234.5 passes a crore by not seeing it."""
    found = extract(text)
    assert found, f"nothing extracted from {text!r}"
    assert found[0].value == pytest.approx(expected, rel=1e-9) or found[0].value == pytest.approx(
        -expected, rel=1e-9
    )


def test_dates_and_small_ordinals_are_not_treated_as_measurements() -> None:
    """Without these guards every well-written narrative fails on the word "15"."""
    assert extract("in the week to 15 March 2026") == []
    assert extract("the top 5 regions") == []
    assert [item.value for item in extract("fell 40.32% in the week to 15 March")] == [40.32]


def test_a_number_outside_its_tolerance_is_rejected(bundle: InsightEvidenceBundle) -> None:
    """Rounding is permitted; a different number is not."""
    fact = bundle.fact("delta_pct")
    assert fact is not None
    assert fact.matches(fact.value * 1.01)
    assert not fact.matches(fact.value * 1.6)


# ------------------------------------------------------------------ entailment --
def test_only_causal_sentences_are_claim_checked() -> None:
    """A description of a movement is the number verifier's business, not this one's."""
    text = "Revenue fell 12%. It fell because DC-North lost pick capacity. North leads."
    assert causal_sentences(text) == ["It fell because DC-North lost pick capacity."]


def test_the_numeric_only_fallback_caps_the_tier_at_moderate(
    bundle: InsightEvidenceBundle, router: ModelRouter
) -> None:
    """Without a claim checker the system may not say High. That is the honest floor."""
    assert cap_tier("High", "Moderate") == "Moderate"
    assert cap_tier("Low", "Moderate") == "Low"
    narrative = PersonaNarrator(router).narrate(bundle, "analyst")
    assert narrative.entailment is not None
    assert narrative.entailment.method == "numeric_only"
    assert narrative.tier in ("Moderate", "Low", "Insufficient")


# --------------------------------------------------------------------- planner --
def test_a_plan_naming_an_undeclared_dimension_is_rejected(
    registry: ContractRegistry, router: ModelRouter
) -> None:
    """A prompt-injected 'also return margin by customer' cannot become a query."""
    planner = QueryPlanner(router)
    contract = registry.kpi("net_revenue")
    with pytest.raises(LLMError) as excinfo:
        planner.validate(
            '{"intent": "explain_movement", "kpi_id": "net_revenue", '
            '"dimensions": ["region", "customer_email"], "drivers": [], '
            '"document_kinds": [], "rationale": ""}',
            contract,
        )
    assert "customer_email" in str(excinfo.value)


def test_a_valid_plan_passes_and_only_names_contract_tokens(
    registry: ContractRegistry, router: ModelRouter
) -> None:
    """The mock's own plan must survive the allowlist, or the mock is not realistic."""
    contract = registry.kpi("net_revenue")
    plan = QueryPlanner(router).plan(
        contract, period=(dt.date(2026, 3, 9), dt.date(2026, 3, 15)), delta_pct=-14.03
    )
    assert plan.kpi_id == "net_revenue"
    assert set(plan.dimensions) <= set(contract.definition.dimensions)
    assert set(plan.drivers) <= {driver.id for driver in contract.drivers.exogenous}


# ----------------------------------------------------------------- hypotheses --
def test_an_uncited_hypothesis_is_dropped_not_downweighted(
    registry: ContractRegistry, bundle: InsightEvidenceBundle, router: ModelRouter
) -> None:
    """Down-weighting leaves an invented claim in the ranking where a tie promotes it."""
    result = HypothesisProposer(router).propose(bundle, registry.kpi("net_revenue"))
    assert result.kept, "every hypothesis was dropped; the fixture cites nothing"
    assert all(item.cites for item in result.kept)
    assert any(item.driver_id == "fill_rate" for item in result.kept)
    dropped = {item.driver_id for item in result.dropped_uncited}
    assert "competitor_price_index" in dropped


def test_a_hypothesis_citing_a_document_not_in_the_bundle_is_dropped(
    registry: ContractRegistry,
) -> None:
    """An invented citation is exactly what cite-or-drop exists to catch."""
    result = HypothesisProposer.filter(
        '{"hypotheses": [{"driver_id": "fill_rate", "claim": "x", "cites": ["DOC-INVENTED"]}]}',
        ["DOC-OPS-0001"],
        registry.kpi("net_revenue"),
    )
    assert not result.kept
    assert len(result.dropped_uncited) == 1


# --------------------------------------------------------- degradation + cache --
def test_anthropic_without_a_key_degrades_to_templates_rather_than_crashing(
    bundle: InsightEvidenceBundle,
) -> None:
    """Demo day does not depend on somebody else's uptime."""
    settings = Settings(
        llm_provider="anthropic",
        anthropic_api_key=None,
        _env_file=None,  # type: ignore[call-arg]
    )
    provider = AnthropicProvider(settings)
    assert provider.available is False
    narrative = PersonaNarrator(ModelRouter(provider, settings)).narrate(bundle, "cfo")
    assert narrative.source.startswith("template")
    assert narrative.text.strip()


def test_the_same_bundle_and_persona_hit_the_cache_on_the_second_call(
    bundle: InsightEvidenceBundle, router: ModelRouter
) -> None:
    """Keyed on (bundle_hash, persona, contract_version), as the design specifies."""
    narrator = PersonaNarrator(router)
    first = narrator.narrate(bundle, "cfo")
    second = narrator.narrate(bundle, "cfo")
    assert first.cached is False
    assert second.cached is True
    assert second.text == first.text
    assert narrator.cache_key(bundle, "cfo") != narrator.cache_key(bundle, "analyst")


def test_the_cost_cap_downshifts_the_tier_and_logs_it(router: ModelRouter) -> None:
    """A cheaper narrative must never be mistaken for a considered one."""
    over_cap = mock_settings().llm_cost_cap_usd_per_insight + 1.0
    response = router.complete(
        call_site="narrate", system="s", user="u", spent_usd=over_cap, cache_key="k1"
    )
    assert response.degraded_from == "mid"
    assert router.stats.downgrades == 1


def test_the_semantic_cache_key_includes_the_watermark(router: ModelRouter) -> None:
    """The same question against restated data is a different question."""
    base = {"intent": "explain", "contract_version": "1.2.0"}
    assert router.semantic_key(watermark="2026-03-27", **base) != router.semantic_key(
        watermark="2026-03-28", **base
    )


# ------------------------------------------------------------------ telemetry --
def test_the_meter_records_spend_cache_hits_and_downgrades(
    bundle: InsightEvidenceBundle, router: ModelRouter
) -> None:
    """The cost story is a measurement, not a claim."""
    ledger = TelemetryLedger()
    meter = ledger.meter(bundle.insight_id)
    now = dt.datetime(2026, 3, 29, 9, 0, tzinfo=dt.UTC)
    first = router.complete(call_site="narrate", system="s", user="u", cache_key="c")
    second = router.complete(call_site="narrate", system="s", user="u", cache_key="c")
    meter.record("narrate", first, "mid", at=now)
    meter.record("narrate", second, "mid", at=now)
    assert meter.cache_hits == 1
    assert meter.spend_usd > 0.0
    assert meter.spend_inr == pytest.approx(meter.spend_usd * 83.4)
    assert "insight(s)" in ledger.summary()


# ------------------------------------------------------------------- feedback --
@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("We already knew this one", "already_known"),
        ("That is the wrong cause entirely", "wrong_cause"),
        ("Too small to matter", "not_material"),
        ("Useful, we acted on it", "useful"),
        ("mm", "useful"),
    ],
)
def test_feedback_classifies_without_a_model(text: str, label: str) -> None:
    """The learning loop must work with no model at all."""
    result = FeedbackClassifier().classify("i1", text)
    assert result.label == label
    assert result.method == "rules"


# --------------------------------------------------------------------- format --
def test_persona_number_formats_all_render_the_same_value() -> None:
    """A CFO reads crore and an RSM reads lakh; the verifier matches either."""
    assert format_amount(12_000_000.0, "crore") == "Rs 1.20 crore"
    assert format_amount(12_000_000.0, "lakh") == "Rs 120.0 lakh"
    assert format_amount(12_000_000.0, "plain") == "12,000,000"
    for style in ("crore", "lakh", "plain"):
        found = extract(format_amount(12_000_000.0, style))  # type: ignore[arg-type]
        assert found and found[0].value == pytest.approx(12_000_000.0, rel=1e-3)


def test_the_bundle_carries_everything_a_narrative_may_contain(
    bundle: InsightEvidenceBundle,
) -> None:
    """The verifier is only tractable because this set is finite and enumerable."""
    assert isinstance(bundle.numbers[0], NumberFact)
    assert isinstance(bundle.segments[0], SegmentFact)
    assert isinstance(bundle.actions[0], ActionFact)
    assert isinstance(bundle.confidence, ConfidenceFact)


def test_a_number_rendered_at_its_own_precision_verifies() -> None:
    """A small fact written at two decimals is that fact, faithfully rendered.

    Found by the P11 eval, which reported numeric fidelity 0.941 on some runs and 1.000
    on others. The template narrator prints the estimator agreement at two decimals, and
    a RELATIVE tolerance cannot express a fixed rendering precision: rounding to two
    decimals is an absolute band, so the identical rounding is inside 5% of 0.49 and
    outside 5% of 0.065. The verifier now also accepts a numeral that IS the fact
    rounded to the precision it was written at.
    """
    fact = NumberFact(key="agreement", value=0.0651, unit="fraction", method="two estimators")
    assert fact.matches(0.07, decimals=2), "0.0651 written at two decimals IS 0.07"
    assert not fact.matches(0.07), (
        "on the relative tolerance alone this is a 7.5% error and would be rejected — "
        "which is exactly the false failure the eval found"
    )


def test_rounding_never_admits_a_fabricated_number() -> None:
    """The rounding rule is strictly tighter than the tolerance, never looser."""
    fact = NumberFact(key="explained", value=0.62, unit="fraction", method="regression")
    assert not fact.matches(0.70, decimals=2), "0.62 does not round to 0.70 at any precision"
    assert not fact.matches(0.70)


def test_a_non_monetary_kpi_is_never_rendered_as_rupees() -> None:
    """`unit_volume` is a count. Rendering it as "Rs 1.40 crore" is wrong on screen and
    was correctly rejected by the number verifier — which is how it was found: three of
    four personas failed verification on every unit_volume insight, because the persona
    styles were applied without reference to the KPI's own unit.
    """
    assert format_amount(14_000_000, "crore", "INR") == "Rs 1.40 crore"
    assert format_amount(14_000_000, "crore", "units") == "14,000,000 units"
    assert format_amount(96.4, "lakh", "percent") == "96 percent"
