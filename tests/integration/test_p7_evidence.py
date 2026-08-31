"""P7 gate — evidence, confidence and actions.

The theme of this phase is what the system does when it *should not* answer. Four of
the seven behaviours below are refusals, and each refuses for a different, named
reason: a stale feed, a missing document, too little history, and a candidate cause
that arrived after the effect it was offered to explain.
"""

from __future__ import annotations

import datetime as dt

import pytest

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.datagen.corpus.models import Document
from insight_copilot.engine.actions import ActionCatalog, ActionSelector, propagate_impact
from insight_copilot.engine.bundle import AbstentionArtifact, InsightEvidenceBundle
from insight_copilot.engine.bundle_mappers import action_numbers
from insight_copilot.engine.calibration import ConfidenceScorer, IsotonicCalibrator
from insight_copilot.engine.confidence import ConfidenceInputs, softmin
from insight_copilot.engine.evidence import EvidenceRetriever, noisy_or
from insight_copilot.engine.pipeline import InsightEngine
from tests.integration.helpers_p7 import (
    NOW,
    OUTAGE_DAY,
    contracts,
    healthy_run,
    make_freshness,
)


@pytest.fixture(scope="module")
def registry() -> ContractRegistry:
    """The shipped contracts."""
    return contracts()


# --------------------------------------------------------------- abstention --
def test_scenario_b_abstains_through_the_data_trust_gate(
    registry: ContractRegistry, world: object
) -> None:
    """A required source past its SLA forces INSUFFICIENT whatever the score says."""
    run = healthy_run(registry, world)
    run.freshness = make_freshness(stale={"martech_weekly"})
    run.required_sources = ["martech_weekly", "oms_orders"]
    result = InsightEngine().run(run, now=NOW)
    assert isinstance(result, AbstentionArtifact)
    assert any("martech_weekly" in check for check in result.failed_checks)
    assert result.confidence.tier == "Insufficient"
    assert result.confidence.signals["c4_data_trust"] < 0.8, result.confidence.signal_detail
    assert "martech_weekly" in result.confidence.signal_detail["c4_data_trust"]
    assert "martech_weekly" in " ".join(result.missing_evidence)
    assert result.retry_trigger
    assert result.eta is not None


def test_a_reconciliation_breach_also_forces_abstention(
    registry: ContractRegistry, world: object
) -> None:
    """Two witnesses disagreeing past the contract's tolerance is a hard gate."""
    run = healthy_run(registry, world)
    run.reconciliation_ok = False
    result = InsightEngine().run(run, now=NOW)
    assert isinstance(result, AbstentionArtifact)
    assert any("reconciliation" in check for check in result.failed_checks)


def test_a_zero_evidence_scenario_abstains_through_the_sufficiency_gate(
    registry: ContractRegistry, world: object
) -> None:
    """Nothing cleared the evidence floor, so nothing is attributed."""
    run = healthy_run(registry, world)
    run.evidence = EvidenceRetriever([]).retrieve(
        "an event nobody wrote about", effect_day=OUTAGE_DAY, floor=0.35
    )
    result = InsightEngine().run(run, now=NOW)
    assert isinstance(result, AbstentionArtifact)
    assert any("evidence" in check.lower() for check in result.failed_checks)
    # An abstention still says what it knows. That is what makes it useful.
    assert len(result.what_is_known) >= 2
    assert any("moved" in line for line in result.what_is_known)


def test_an_abstention_is_a_designed_output_not_an_error(
    registry: ContractRegistry, world: object
) -> None:
    """It carries movement, knowns, failures, gaps, a retry trigger and an ETA."""
    run = healthy_run(registry, world)
    run.freshness = make_freshness(stale={"oms_orders"})
    run.required_sources = ["oms_orders"]
    result = InsightEngine().run(run, now=NOW)
    assert isinstance(result, AbstentionArtifact)
    assert result.observed_movement
    assert result.failed_checks and result.missing_evidence
    assert result.headline.startswith("net_revenue")
    assert result.freshness, "the abstention must show the freshness that caused it"


# --------------------------------------------------------------- the insight --
def test_a_healthy_run_produces_a_bundle_with_actions(
    registry: ContractRegistry, world: object
) -> None:
    """Everything present and fresh: an insight, priced, owned and monitored."""
    result = InsightEngine().run(healthy_run(registry, world), now=NOW)
    assert isinstance(result, InsightEvidenceBundle)
    assert result.confidence.tier in ("High", "Moderate")
    assert result.permits_recommendation
    assert result.actions, "a Moderate-or-better insight carried no action"
    action = result.actions[0]
    assert action.expected_impact_low < action.expected_impact_high
    assert action.owner_role and action.monitoring_kpi
    assert action.monitoring_checkpoints


def test_every_narratable_number_is_in_the_bundle(
    registry: ContractRegistry, world: object
) -> None:
    """The verifier's whole tractability rests on this set being finite and complete."""
    result = InsightEngine().run(healthy_run(registry, world), now=NOW)
    assert isinstance(result, InsightEvidenceBundle)
    keys = {item.key for item in result.narratable_values}
    assert {"observed", "counterfactual", "delta", "delta_pct", "p_value"} <= keys
    assert {"price_effect", "volume_effect", "mix_effect"} <= keys
    fact = result.fact("delta_pct")
    assert fact is not None and fact.matches(result.delta_pct)
    assert not fact.matches(result.delta_pct + 5.0)


def test_the_bundle_carries_lineage_and_freshness(
    registry: ContractRegistry, world: object
) -> None:
    """Freshness, method, contribution, confidence and lineage accompany every insight."""
    result = InsightEngine().run(healthy_run(registry, world), now=NOW)
    assert isinstance(result, InsightEvidenceBundle)
    assert result.lineage, "no lineage on the card"
    assert {step.stage for step in result.lineage} <= {"land", "conform", "mart", "blend"}
    assert result.freshness
    assert result.confidence.signal_detail["c3_statistical"]


# ------------------------------------------------------------ sparse history --
def test_scenario_c_is_not_flagged_and_names_its_own_sample_size(
    registry: ContractRegistry, world: object
) -> None:
    """Eighteen days of history caps what may be said, and says why."""
    run = healthy_run(registry, world)
    run.history_days = 18
    result = InsightEngine().run(run, now=NOW)
    # Both output types carry the same confidence block, which is the point: the
    # reason for the restraint is legible whichever way the run came out.
    detail = result.confidence.signal_detail["c3_statistical"]
    assert "n = 18" in detail, detail
    assert "28-day floor" in detail
    assert result.confidence.tier in ("Moderate", "Low", "Insufficient")
    full = InsightEngine().run(healthy_run(registry, world), now=NOW)
    assert result.confidence.calibrated < full.confidence.calibrated


# ----------------------------------------------------------------- evidence --
def test_the_post_dated_decoy_is_eliminated_by_the_timing_gate() -> None:
    """A cause cannot post-date its effect, however well it scores on relevance."""
    decoy = _document(
        "DOC-DECOY", "Competitor launches aggressive price campaign", dt.date(2026, 3, 16)
    )
    real = _document("DOC-REAL", "DC-North pick capacity failure", dt.date(2026, 3, 6))
    bundle = EvidenceRetriever([decoy, real]).retrieve(
        "north warehouse capacity failure price campaign", effect_day=OUTAGE_DAY, floor=0.1
    )
    kept = {item.document.doc_id for item in bundle.items}
    assert "DOC-DECOY" in bundle.rejected_by_timing
    assert kept == {"DOC-REAL"}


def test_syndicated_copies_count_as_one_independent_source() -> None:
    """Without the dedup, noisy-OR reads one press release as six confirmations."""
    copies = [
        _document(
            f"DOC-{index}",
            "Meridian confirms warehouse disruption",
            dt.date(2026, 3, 6),
            syndication="SYN-1",
        )
        for index in range(6)
    ]
    bundle = EvidenceRetriever(copies).retrieve(
        "warehouse disruption", effect_day=OUTAGE_DAY, floor=0.1
    )
    assert bundle.independent_sources == 1
    assert len(bundle.items) == 1
    single = bundle.items[0].confidence
    assert 0.0 <= single <= 1.0, "BM25's negative IDF must not reach a card"
    assert bundle.corroboration == pytest.approx(single, abs=1e-9)
    # The guard is only meaningful because six copies would otherwise inflate.
    assert noisy_or([0.6] * 6) > 1.4 * noisy_or([0.6])


def test_a_document_is_matched_on_its_effective_date_not_its_publish_date() -> None:
    """A February memo effective in April must be findable from April."""
    memo = Document(
        doc_id="DOC-MEMO",
        kind="pricing_memo",
        title="Haircare list price revision",
        body="A 8% list price increase across the haircare range.",
        publish_date=dt.date(2026, 1, 20),
        effective_date=dt.date(2026, 3, 1),
        source_tier=1,
    )
    bundle = EvidenceRetriever([memo]).retrieve(
        "haircare list price increase", effect_day=dt.date(2026, 3, 9), floor=0.1
    )
    assert [item.document.doc_id for item in bundle.items] == ["DOC-MEMO"]
    assert bundle.items[0].matched_on == "effective_date"


# --------------------------------------------------------------- confidence --
def test_softmin_is_dominated_by_the_weakest_signal() -> None:
    """A chain is as strong as its weakest link; a mean would hide that."""
    strong = [0.95, 0.95, 0.95, 0.95, 0.95, 0.95]
    one_weak = [0.95, 0.95, 0.95, 0.20, 0.95, 0.95]
    assert softmin(strong) > 0.9
    assert softmin(one_weak) < 0.35
    assert softmin(one_weak) > min(one_weak) * 0.9
    # Strictly between the minimum and the arithmetic mean, which is the whole design.
    assert min(one_weak) < softmin(one_weak) < sum(one_weak) / len(one_weak)


def test_calibration_reports_itself_as_unfitted_until_a_backtest_exists() -> None:
    """An uncalibrated score must never be presented as a probability."""
    calibrator = IsotonicCalibrator()
    assert calibrator.fitted is False
    assert calibrator.transform(0.62) == pytest.approx(0.62)


def test_any_signal_below_the_contract_floor_forces_insufficient(
    registry: ContractRegistry,
) -> None:
    """The contract's ``any_signal_min`` is a gate, not a term in an average."""
    contract = registry.kpi("net_revenue")
    inputs = ConfidenceInputs(
        p_value=0.0001,
        materiality_ratio=8.0,
        bootstrap_stability=0.96,
        attribution_coverage=0.85,
        ljung_box_p=0.4,
        breusch_pagan_p=0.3,
        estimator_agreement=0.95,
        history_days=900,
        evidence_corroboration=0.05,
        independent_sources=1,
        timing_gate_survivors=1,
    )
    result = ConfidenceScorer().score(inputs, contract)
    assert result.tier == "Insufficient"
    assert any(
        "c5_evidence" in failure or "evidence" in failure for failure in result.hard_gate_failures
    )


# ------------------------------------------------------------------ actions --
def test_actions_are_suppressed_at_low_and_insufficient(
    registry: ContractRegistry, world: object
) -> None:
    """A recommendation the system is not confident in is worse than silence."""
    run = healthy_run(registry, world)
    run.evidence = EvidenceRetriever([]).retrieve("nothing", effect_day=OUTAGE_DAY, floor=0.35)
    result = InsightEngine().run(run, now=NOW)
    assert isinstance(result, AbstentionArtifact)
    assert not hasattr(result, "actions")


def test_expected_impact_carries_its_interval_never_a_point() -> None:
    """The interval is what makes the number a basis for a decision."""
    impact = propagate_impact(
        baseline_value=1.0e8,
        elasticity=-1.63,
        elasticity_interval=(-3.01, -0.26),
        lever_change=-0.08,
        effect_fraction=1.0,
    )
    assert impact.low < impact.central < impact.high
    assert impact.low > 0.0, "a price reversal against a negative elasticity recovers revenue"
    assert "95% interval" in impact.detail


def test_an_action_whose_precondition_fails_is_not_proposed(
    registry: ContractRegistry, world: object
) -> None:
    """Preconditions are checked against live data, and an unchecked one is not met."""
    catalog = ActionCatalog.load("catalogs/actions_revenue.yaml")
    selector = ActionSelector(catalog)
    scorer = ConfidenceScorer()
    confidence = scorer.score(
        ConfidenceInputs(
            p_value=0.001,
            materiality_ratio=6.0,
            bootstrap_stability=0.95,
            attribution_coverage=0.9,
            ljung_box_p=0.4,
            breusch_pagan_p=0.4,
            estimator_agreement=0.95,
            history_days=900,
            evidence_corroboration=0.8,
            independent_sources=3,
            timing_gate_survivors=3,
        ),
        registry.kpi("net_revenue"),
    )
    common = {
        "contract": registry.kpi("net_revenue"),
        "driver_id": "price_index",
        "confidence": confidence,
        "baseline_value": 1.0e8,
        "elasticity": -1.63,
        "elasticity_interval": (-3.01, -0.26),
        "lever_change": -0.08,
        # Revenue came in below its baseline, so an admissible action has to push it back
        # up. With a negative elasticity and a price cut, both candidates do.
        "gap": -5.0e7,
        "today": NOW.date(),
    }
    passing = selector.select(
        observed={"price_index": 1.08, "discount_depth_pct": 12.0, "gross_margin_pct": 48.0},
        **common,
    )
    failing = selector.select(
        observed={"price_index": 0.99, "discount_depth_pct": 12.0, "gross_margin_pct": 48.0},
        **common,
    )
    unevaluable = selector.select(observed={"price_index": 1.08}, **common)
    assert {item.spec.id for item in passing.chosen} == {
        "reverse_price_increase",
        "targeted_promotion_in_affected_segment",
    }
    assert passing.withheld == []
    # The price index no longer clears the reversal's precondition, so that action is
    # withheld; the promotion, whose conditions are unrelated and still hold, is not.
    assert {item.spec.id for item in failing.chosen} == {"targeted_promotion_in_affected_segment"}
    assert any("failed" in reason for reason in failing.withheld)
    assert {item.spec.id for item in unevaluable.chosen} == {"reverse_price_increase"}, (
        "an action was proposed on preconditions that could not be evaluated"
    )
    assert any("could not check" in reason for reason in unevaluable.withheld), (
        "an unevaluable precondition must be reported as such, not as a failure"
    )


def test_an_action_that_would_widen_the_gap_is_not_proposed(
    registry: ContractRegistry, world: object
) -> None:
    """The catalog's intuition does not overrule the elasticity actually estimated.

    A promotion is priced with the coefficient the regression returned. When that
    coefficient says demand is inelastic, cutting price is priced as a *loss*, and an
    action whose own arithmetic makes the movement worse is not a recommendation.
    """
    catalog = ActionCatalog.load("catalogs/actions_revenue.yaml")
    selector = ActionSelector(catalog)
    confidence = ConfidenceScorer().score(
        ConfidenceInputs(
            p_value=0.001,
            materiality_ratio=6.0,
            bootstrap_stability=0.95,
            attribution_coverage=0.9,
            ljung_box_p=0.4,
            breusch_pagan_p=0.4,
            estimator_agreement=0.95,
            history_days=900,
            evidence_corroboration=0.8,
            independent_sources=3,
            timing_gate_survivors=3,
        ),
        registry.kpi("net_revenue"),
    )
    selection = selector.select(
        contract=registry.kpi("net_revenue"),
        driver_id="price_index",
        confidence=confidence,
        baseline_value=1.0e8,
        # A POSITIVE price elasticity of revenue: inelastic demand, so a price cut loses
        # money. This is the sign the estimator actually returns on this build.
        elasticity=0.93,
        elasticity_interval=(0.31, 1.55),
        lever_change=-0.08,
        observed={"price_index": 1.08, "discount_depth_pct": 12.0, "gross_margin_pct": 48.0},
        gap=-5.0e7,
        today=NOW.date(),
    )

    assert selection.chosen == []
    assert selection.withheld, "the refusal must be reported, not merely logged"
    assert any("wrong way" in reason for reason in selection.withheld)


def _document(
    doc_id: str, title: str, effective: dt.date, *, syndication: str | None = None
) -> Document:
    """A minimal corpus document for the retrieval tests."""
    return Document(
        doc_id=doc_id,
        kind="ops_incident" if "capacity" in title else "news_article",
        title=title,
        body=f"{title}. Operations reported the incident affecting the North region.",
        publish_date=effective,
        effective_date=effective,
        source_tier=2,
        syndication_group=syndication,
    )


def test_a_proposed_action_carries_facts_for_the_numbers_it_will_be_narrated_with(
    registry: ContractRegistry, world: object
) -> None:
    """The recommendation sentence quotes three figures; all three must be verifiable.

    They were not. The pipeline emitted the action but no facts for its priced impact,
    so a faithful sentence failed the number verifier and every persona fell back to the
    template it had already rendered. The unit fixture happened to hand-write those
    facts, which is exactly why the gap survived: the test could not see it.
    """
    catalog = ActionCatalog.load("catalogs/actions_revenue.yaml")
    confidence = ConfidenceScorer().score(
        ConfidenceInputs(
            p_value=0.001,
            materiality_ratio=6.0,
            bootstrap_stability=0.95,
            attribution_coverage=0.9,
            ljung_box_p=0.4,
            breusch_pagan_p=0.4,
            estimator_agreement=0.95,
            history_days=900,
            evidence_corroboration=0.8,
            independent_sources=3,
            timing_gate_survivors=3,
        ),
        registry.kpi("net_revenue"),
    )
    selection = ActionSelector(catalog).select(
        contract=registry.kpi("net_revenue"),
        driver_id="price_index",
        confidence=confidence,
        baseline_value=1.0e8,
        elasticity=-1.63,
        elasticity_interval=(-3.01, -0.26),
        lever_change=-0.08,
        observed={"price_index": 1.08, "discount_depth_pct": 12.0, "gross_margin_pct": 48.0},
        gap=-5.0e7,
        today=NOW.date(),
    )
    assert selection.chosen, "the fixture is meant to produce at least one action"

    facts = action_numbers(selection.chosen, "INR")
    values = {round(fact.value, 6) for fact in facts}
    for action in selection.chosen:
        impact = action.expected_impact
        assert round(impact.central, 6) in values
        assert round(impact.low, 6) in values
        assert round(impact.high, 6) in values
    # Keyed by action id so two proposals cannot overwrite each other's price.
    assert len({fact.key for fact in facts}) == 3 * len(selection.chosen)
