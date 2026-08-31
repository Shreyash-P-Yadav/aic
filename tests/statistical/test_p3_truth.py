"""P3 gate — events and ground truth.

Two things are being proved. First, that the *machinery* is exact: Shapley
contributions over interacting events sum to the observed gap with no residual, so
attribution accuracy can be scored against a number with no slack in it. Second, that
the *scenarios* are the ones the demo needs: Scenario A moves about -12%, Scenario C's
launch is genuinely sparse, and the calibration corpus spans the four axes that move
the confidence score.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

import pytest

from insight_copilot.datagen.events.build import build_full_ledger
from insight_copilot.datagen.events.effects import LedgerOverlay
from insight_copilot.datagen.events.ledger import EventLedger
from insight_copilot.datagen.events.models import Event
from insight_copilot.datagen.simulate import Simulator
from insight_copilot.datagen.truth.counterfactual import (
    SEPARATION_DAYS,
    CounterfactualRunner,
    group_interacting_events,
)
from insight_copilot.datagen.truth.planner import build_run_plan
from insight_copilot.datagen.truth.shapley import shapley_contributions

pytestmark = pytest.mark.statistical

SCENARIO_A_WEEK = (dt.date(2026, 3, 9), dt.date(2026, 3, 15))
SCENARIO_A_TARGET_PCT = -12.0
"""The design's target for the flagship week. The gate allows 1pp either side."""


@pytest.fixture(scope="module")
def scenarios() -> EventLedger:
    return EventLedger.from_scenarios()


@pytest.fixture(scope="module")
def scenario_a(scenarios: EventLedger) -> list[Event]:
    """The three interacting causes of Scenario A, in ledger order."""
    roles = ("scenario_A_primary", "scenario_A_media", "scenario_A_price")
    return [event for event in scenarios if event.demo_role in roles]


@pytest.fixture(scope="module")
def full_ledger(simulator: Simulator) -> EventLedger:
    return build_full_ledger(simulator.config, simulator.catalog, simulator.seeds)


@pytest.fixture(scope="module")
def scenario_a_truth(simulator: Simulator, scenario_a: list[Event]) -> tuple[object, float, float]:
    """Shapley over Scenario A's three events, plus the factual and counterfactual weeks.

    Eight full simulations (2**3). Computed once for the module.
    """
    runner = CounterfactualRunner(simulator, scenario_a)
    window = runner.factual.window(*SCENARIO_A_WEEK)

    def value_of(panel: object) -> float:
        return float(panel.net_revenue_by_day()[window].sum())  # type: ignore[attr-defined]

    result = shapley_contributions(runner=runner, events=tuple(scenario_a), value_of=value_of)
    factual = value_of(runner.factual)
    counterfactual = value_of(runner.without({event.event_id for event in scenario_a}))
    return result, factual, counterfactual


# ================================================== the Shapley guarantee =====
def test_shapley_contributions_sum_to_the_observed_gap(
    scenario_a_truth: tuple[object, float, float],
) -> None:
    """The headline guarantee: exact, additive, order-independent, no residual.

    One-at-a-time counterfactuals would NOT sum here, because the three events
    genuinely interact — a stockout suppresses exactly the volume the marketing cut
    would otherwise have removed. Shapley shares the interaction out instead of
    leaving a residual to explain away.
    """
    result, factual, counterfactual = scenario_a_truth
    observed_gap = factual - counterfactual
    total = sum(result.contributions.values())  # type: ignore[attr-defined]

    assert result.method == "shapley_within_window"  # type: ignore[attr-defined]
    assert result.n_runs == 8  # type: ignore[attr-defined]
    assert abs(total - observed_gap) <= abs(observed_gap) * 0.01, (
        f"contributions sum to {total:,.0f} against an observed gap of {observed_gap:,.0f}"
    )
    # Far tighter than the 1% the gate asks for: the identity is exact, so the only
    # error is floating point.
    assert abs(total - observed_gap) < max(1e-6, abs(observed_gap) * 1e-12)


def test_one_at_a_time_deltas_do_not_sum_and_shapley_does(
    simulator: Simulator, scenario_a: list[Event], scenario_a_truth: tuple[object, float, float]
) -> None:
    """The reason Shapley is needed rather than three counterfactuals.

    If the events did not interact this test would be vacuous, so it asserts the
    interaction is real: the naive sum misses the total by a measurable amount, and
    Shapley closes it exactly.
    """
    result, factual, counterfactual = scenario_a_truth
    runner = CounterfactualRunner(simulator, scenario_a)
    window = runner.factual.window(*SCENARIO_A_WEEK)

    def value_of(panel: object) -> float:
        return float(panel.net_revenue_by_day()[window].sum())  # type: ignore[attr-defined]

    naive_sum = sum(factual - value_of(runner.without({event.event_id})) for event in scenario_a)
    observed_gap = factual - counterfactual
    interaction = abs(naive_sum - observed_gap)

    assert interaction > 0.0, "the three events do not interact, so Shapley proves nothing"
    assert abs(sum(result.contributions.values()) - observed_gap) < interaction  # type: ignore[attr-defined]


def test_every_scenario_a_event_carries_a_contribution(
    scenario_a_truth: tuple[object, float, float],
) -> None:
    result, _, _ = scenario_a_truth
    contributions = result.contributions  # type: ignore[attr-defined]
    assert set(contributions) == {
        "EV-2026-0306-OUTAGE",
        "EV-2026-0224-MEDIACUT",
        "EV-2026-0301-PRICERISE",
    }
    assert all(value < 0 for value in contributions.values()), (
        "every planted cause of a revenue drop should reduce revenue"
    )


# ================================================ scenario A's magnitude ======
def test_scenario_a_moves_revenue_by_about_twelve_percent(
    scenario_a_truth: tuple[object, float, float],
) -> None:
    """Within 1pp of the -12% target for the week commencing 9 Mar 2026."""
    _, factual, counterfactual = scenario_a_truth
    movement_pct = 100.0 * (factual / counterfactual - 1.0)
    assert abs(movement_pct - SCENARIO_A_TARGET_PCT) <= 1.0, (
        f"Scenario A moved {movement_pct:+.2f}%, target {SCENARIO_A_TARGET_PCT:+.1f}% +/- 1pp"
    )


def test_the_outage_shows_up_as_a_fill_rate_collapse_at_dc_north(
    simulator: Simulator, scenario_a: list[Event]
) -> None:
    """The outage must be visible in the KPI it directly damages, not only in revenue."""
    runner = CounterfactualRunner(simulator, scenario_a)
    outage_window = runner.factual.window(dt.date(2026, 3, 6), dt.date(2026, 3, 12))
    row = simulator.config.warehouse_ids.index("DC-North")

    def fill_rate(panel: object) -> float:
        ordered = panel.units_ordered[row, :, outage_window].sum()  # type: ignore[attr-defined]
        shipped = panel.units_shipped_ok[row, :, outage_window].sum()  # type: ignore[attr-defined]
        return float(shipped / ordered)

    without = runner.without({"EV-2026-0306-OUTAGE"})
    assert fill_rate(without) > 0.95, "the baseline DC-North fill rate is not healthy"
    assert fill_rate(runner.factual) < 0.55, "the outage did not damage fill rate"


# ================================================= the calibration corpus =====
def test_the_calibration_corpus_has_at_least_four_hundred_events(
    full_ledger: EventLedger,
) -> None:
    assert len(full_ledger.calibration_events) >= 400


def test_scenario_events_are_tagged_for_exclusion_from_the_fit(
    full_ledger: EventLedger,
) -> None:
    """Otherwise the demo cases would be scored by a map trained on themselves."""
    scenario = full_ledger.scenario_events
    assert len(scenario) == 8
    assert all(event.is_scenario for event in scenario)
    assert not any(event.is_scenario for event in full_ledger.calibration_events)


def test_the_corpus_spreads_magnitude(full_ledger: EventLedger) -> None:
    """Axis 1: just-below-materiality to very large, so c1 varies across the corpus."""
    counts = Counter(event.detectability for event in full_ledger.calibration_events)
    assert counts["low"] >= 40, "no near-threshold events to exercise the materiality gate"
    assert counts["high"] >= 40, "no large events to anchor the top of the score range"
    assert counts["medium"] >= 40


def test_the_corpus_spreads_segment_concentration(full_ledger: EventLedger) -> None:
    """Axis 2: one SKU to a whole category across regions, so c2 varies."""
    events = full_ledger.calibration_events
    concentrated = sum(1 for event in events if event.scope.skus)
    single_region = sum(
        1 for event in events if len(event.scope.regions) == 1 and not event.scope.skus
    )
    diffuse = sum(1 for event in events if len(event.scope.regions) > 1)
    for label, count in (
        ("concentrated", concentrated),
        ("single-region", single_region),
        ("diffuse", diffuse),
    ):
        assert count >= 40, f"only {count} {label} events"


def test_the_corpus_spreads_evidence_availability(full_ledger: EventLedger) -> None:
    """Axis 3: including deliberate evidence GAPS, which is what exercises abstention."""
    events = full_ledger.calibration_events
    no_documents = [event for event in events if event.evidence.documents == 0]
    well_evidenced = [event for event in events if event.evidence.documents >= 4]
    decoys = [event for event in events if event.evidence.post_dated_decoy]

    gap_rate = len(no_documents) / len(events)
    assert 0.08 <= gap_rate <= 0.22, f"evidence-gap rate {gap_rate:.3f}, design target ~15%"
    assert len(well_evidenced) >= 40
    assert len(decoys) >= 15, "no post-dated decoys to exercise the timing gate"


def test_the_corpus_spreads_data_condition(full_ledger: EventLedger) -> None:
    """Axis 4: clean through stale feed and reconciliation breach, so c4 varies."""
    counts = Counter(event.data_condition for event in full_ledger.calibration_events)
    assert set(counts) == {"clean", "stale_feed", "reconciliation_breach", "restatement_open"}
    assert counts["clean"] / sum(counts.values()) > 0.35, (
        "most of the corpus must be clean, or the calibration curve describes a "
        "broken pipeline rather than a working one"
    )
    for condition in ("stale_feed", "reconciliation_breach", "restatement_open"):
        assert counts[condition] >= 40, f"only {counts[condition]} {condition} events"


# ============================================== ground-truth tractability =====
def test_the_ground_truth_plan_is_affordable(full_ledger: EventLedger) -> None:
    """Batching independent events must keep the whole ledger inside its time budget.

    Without it, several hundred events would need several hundred full simulations
    and the calibration corpus would be unaffordable — which is the point of the
    lane layout in the calibration generator.
    """
    mechanical = [
        event
        for event in full_ledger
        if event.ground_truth.compute and event.magnitude.kind != "none"
    ]
    groups = group_interacting_events(mechanical)
    plan = build_run_plan(groups)

    assert len(mechanical) >= 400
    assert plan.n_runs < len(mechanical) / 2, (
        f"{plan.n_runs} runs for {len(mechanical)} events — batching is not working"
    )
    # At ~2.6 s a run, the design's budget for this one-off job is 20 minutes.
    assert plan.n_runs * 2.6 < 20 * 60


def test_events_far_apart_and_disjoint_in_scope_are_independent(
    full_ledger: EventLedger,
) -> None:
    """The property the batching rests on, asserted directly."""
    events = full_ledger.calibration_events
    groups = group_interacting_events(events)
    for group in groups:
        for one in group.events:
            others = [other for other in group.events if other is not one]
            if not others:
                continue
            assert any(
                one.scope.may_interact_with(other.scope)
                and abs((one.window.start - other.window.end).days) <= SEPARATION_DAYS + 200
                for other in others
            ), f"{one.event_id} is in a group with nothing it can interact with"


# =============================================== the remaining scenarios ======
def test_scenario_b_is_a_data_incident_with_no_mechanical_effect(
    scenarios: EventLedger,
) -> None:
    """Nothing is wrong with the business; something is wrong with what we know.

    If Scenario B moved demand, the abstention would be explaining a real movement
    rather than refusing to explain an artefact — which is the opposite of the point.
    """
    events = [event for event in scenarios if (event.demo_role or "").startswith("scenario_B")]
    assert len(events) == 2
    assert all(event.type == "data_incident" for event in events)
    assert all(event.magnitude.kind == "none" for event in events)
    assert all(not event.ground_truth.compute for event in events)


def test_scenario_c_launch_has_eighteen_days_of_history_at_sim_today(
    simulator: Simulator, scenarios: EventLedger
) -> None:
    """Below the net_revenue contract's 28-day minimum for full statistics."""
    aurora = next(sku for sku in simulator.catalog.skus if sku.name.startswith("Aurora X"))
    sim_today = dt.date(2026, 3, 29)
    days = (sim_today - aurora.launch_date).days
    assert days == 18

    promo = scenarios.by_id("EV-2026-0311-AURORA-LAUNCH-PROMO")
    assert promo.scope.skus == [aurora.sku_id]
    # The promo expires on day 14, which is what produces the day-15-to-20 dip the
    # engine must recognise as ordinary rather than flag as an anomaly.
    assert (promo.window.end - promo.window.start).days == 13


def test_scenario_d_plants_no_data_at_all(scenarios: EventLedger) -> None:
    """The entitlement demo happens in the compiler, on identical underlying numbers."""
    event = scenarios.by_demo_role("scenario_D_primary")[0]
    assert event.magnitude.kind == "none"
    assert not event.ground_truth.compute


def test_the_post_dated_decoy_lands_after_the_effect_it_would_explain(
    scenarios: EventLedger,
) -> None:
    """The timing gate's test case: topically relevant, and impossible."""
    decoy = scenarios.by_demo_role("scenario_A_decoy")[0]
    assert decoy.evidence.post_dated_decoy
    assert decoy.window.start > SCENARIO_A_WEEK[1], (
        "the decoy must post-date the movement it appears to explain"
    )
    assert decoy.evidence.syndication >= 3, "a decoy nobody repeated is not tempting"


# ================================================= the ledger end to end ======
def test_the_ground_truth_ledger_is_written_and_exact(
    simulator: Simulator, scenario_a: list[Event], tmp_path: object
) -> None:
    """Run the whole ground-truth pipeline over Scenario A and check the artefact.

    Deliberately scoped to three events (eight simulations) rather than the full
    445-event ledger, which takes about six minutes and is produced by
    ``make generate-truth``. What is proved here is the *pipeline*: plan, simulate,
    measure, Shapley, write — and that the identity survives the round trip to disk.
    """
    from pathlib import Path as _Path

    import pandas as pd

    from insight_copilot.datagen.truth.ledger_writer import GroundTruthComputer, write_ledger

    truth = GroundTruthComputer(simulator, scenario_a).compute()
    assert truth.n_events == 3
    assert truth.n_runs == 8

    directory = _Path(str(tmp_path))
    path = write_ledger(truth, directory)
    frame = pd.read_parquet(path)

    required = {
        "event_id",
        "group_id",
        "event_set",
        "true_contribution_inr",
        "group_total_inr",
        "group_method",
        "scoped_delta_pct",
        "true_top_region",
        "true_top_category",
        "excluded_from_calibration_fit",
    }
    assert required <= set(frame.columns)
    assert frame["excluded_from_calibration_fit"].all(), "scenario events must be tagged"

    for _, group in frame.groupby("group_id"):
        if group["group_method"].iloc[0] != "shapley_within_window":
            continue
        total = float(group["group_total_inr"].iloc[0])
        assert abs(group["true_contribution_inr"].sum() - total) < max(1e-6, abs(total) * 1e-12)

    # The outage's damage must be visible inside its own scope, not diluted to
    # nothing by measuring a DC-North failure against national revenue.
    outage = frame.loc[frame["event_id"] == "EV-2026-0306-OUTAGE"].iloc[0]
    assert outage["scoped_delta_pct"] < -3.0
    assert abs(outage["scoped_delta_pct"]) > abs(outage["isolated_delta_pct"])


# ===================================================== the event overlay ======
def test_an_event_removed_from_the_overlay_leaves_no_trace(
    simulator: Simulator, scenario_a: list[Event]
) -> None:
    """Dropping an event must be equivalent to it never having been authored."""
    overlay = LedgerOverlay(
        scenario_a,
        config=simulator.config,
        catalog=simulator.catalog,
        cells=simulator.assortment,
        horizon_start=simulator.config.horizon.start,
    )
    dropped = overlay.without({"EV-2026-0306-OUTAGE"})
    rebuilt = LedgerOverlay(
        [event for event in scenario_a if event.event_id != "EV-2026-0306-OUTAGE"],
        config=simulator.config,
        catalog=simulator.catalog,
        cells=simulator.assortment,
        horizon_start=simulator.config.horizon.start,
    )
    assert simulator.run(dropped).checksum() == simulator.run(rebuilt).checksum()
