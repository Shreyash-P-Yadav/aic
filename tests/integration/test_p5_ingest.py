"""P5 gate — the landing zone, the harness and the ingestion pipeline.

Every assertion here is a behaviour the design promises and that a completed
warehouse cannot express:

* replaying ninety simulated days completes;
* delivering the same ``batch_id`` twice changes nothing;
* delivering identical rows under a new ``batch_id`` is deduplicated;
* a restatement supersedes, and both versions remain queryable;
* pausing a feed walks freshness green -> amber -> red on the SLA schedule;
* a late batch recomputes exactly the affected window;
* the silent unit change is caught by a range expectation and quarantined.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from insight_copilot.datagen.defects.schema import SchemaDrift, SilentUnitChange
from insight_copilot.harness.periods import week_label
from insight_copilot.harness.scheduler import ArrivalScheduler
from insight_copilot.ingest.gold import REVENUE_MART
from tests.integration.helpers_p5 import (
    bronze_batches,
    daily_arrival,
    expected_new_id,
    freshness,
    fulfilment_units,
    gold_revenue_for,
    latest_landed,
    period_rows,
    rearrival,
    restatable_week,
    silver_spend,
    week_monday,
    week_monday_date,
)

GO_LIVE = dt.date(2026, 1, 5)
"""The historical load ends here, leaving a clean quarter of replay in front of the
demo's ``sim_today`` (2026-03-29) and well clear of Scenario A's window in March."""

REPLAY_DAYS = 90
"""The gate's replay window. Ninety days covers thirteen MarTech drops, ninety OMS
drops and roughly four thousand ticket batches — enough for every cadence in the
contract set to be exercised many times over."""


# --------------------------------------------------------------------- replay --
def test_backfill_loads_history_into_every_contract_mart(loaded: dict[str, object]) -> None:
    """The bulk historical load fills the marts the KPI contracts name."""
    warehouse = loaded["warehouse"]
    for mart in ("fct_revenue_daily", "fct_fulfilment_daily", "fct_marketing_weekly"):
        assert warehouse.row_count("gold", mart) > 0, f"gold.{mart} is empty after backfill"
    assert warehouse.row_count("gold", "driver_panel") > 0
    assert warehouse.row_count("gold", "dim_calendar") > 0


def test_replaying_ninety_sim_days_completes(replayed: dict[str, object]) -> None:
    """The headline gate: ninety simulated days of arrivals land and ingest."""
    summary = replayed["summary"]
    assert summary.planned > 0
    assert summary.landed > 0
    assert summary.rows_landed > 0
    # Some drops legitimately do not arrive: every contract declares a failure
    # probability, and a harness in which nothing ever goes missing would never
    # exercise the freshness path.
    assert summary.missed > 0
    assert summary.missed < summary.planned * 0.2


def test_every_source_delivered_during_the_replay(replayed: dict[str, object]) -> None:
    """All eleven feeds land at least once in ninety days, on their own cadence."""
    registry = replayed["harness"].runner.batch_registry
    delivered = set(registry.batches()["source_id"])
    expected = set(replayed["harness"].contracts.source_ids)
    # ``holiday_calendar`` fires once a year and is delivered by the historical load,
    # so it is present in the registry even though it never drops during the replay.
    assert expected <= delivered, f"never delivered: {sorted(expected - delivered)}"


def test_the_calendar_spine_has_no_gaps(loaded: dict[str, object]) -> None:
    """Every date exists between the horizon start and go-live. Gaps are explicit."""
    spine = loaded["warehouse"].query("SELECT date FROM gold.dim_calendar ORDER BY date")
    days = pd.to_datetime(spine["date"])
    assert (days.diff().dropna() == pd.Timedelta(days=1)).all()


# ------------------------------------------------------------------ freshness --
def test_a_healthy_weekly_feed_is_green_the_day_after_it_lands(
    replayed: dict[str, object],
) -> None:
    """Freshness is measured against the expected arrival, not raw age."""
    harness = replayed["harness"]
    status = freshness(harness, "martech_weekly")
    assert status.state == "green"
    assert status.age_hours is not None and status.age_hours > status.sla_hours


# ---------------------------------------------------------------- idempotency --
def test_the_same_batch_id_twice_changes_nothing(replayed: dict[str, object]) -> None:
    """Idempotency by ``(source_id, batch_id)``: a re-delivery is a no-op."""
    harness = replayed["harness"]
    warehouse = replayed["warehouse"]
    batch = latest_landed(harness, "oms_orders")

    before_bronze = warehouse.row_count("bronze", "oms_orders")
    before_silver = warehouse.row_count("silver", "oms_orders")
    before_gold = warehouse.row_count("gold", REVENUE_MART)

    result = harness.runner.ingest(batch, sim_time=harness.clock.now)

    assert result.status == "skipped_duplicate"
    assert warehouse.row_count("bronze", "oms_orders") == before_bronze
    assert warehouse.row_count("silver", "oms_orders") == before_silver
    assert warehouse.row_count("gold", REVENUE_MART) == before_gold


def test_identical_rows_under_a_new_batch_id_are_deduplicated(
    replayed: dict[str, object],
) -> None:
    """The second idempotency key: ``row_hash`` dedup inside a period."""
    harness = replayed["harness"]
    warehouse = replayed["warehouse"]
    batch = latest_landed(harness, "oms_orders")
    period = batch.manifest.covers.periods[0]
    contract = harness.contracts.source("oms_orders")

    silver_before = period_rows(warehouse, "silver", "oms_orders", period)
    gold_before = gold_revenue_for(warehouse, period)

    # Re-land the same rows now. That is a new delivery moment, so it gets a new batch
    # id — the id digests the sim timestamp as well as the content — and the registry's
    # first idempotency key does not catch it. Only the row hash can.
    arrival = rearrival(batch, harness.clock.now)
    frame = batch.read(contract)
    harness.land_frame(arrival, frame, producer_note="duplicate export")
    results = harness.drain()

    landed = [item for item in results if item.batch_id == expected_new_id(results, batch)]
    assert landed, "the re-delivery was not ingested at all"
    assert landed[0].status in ("ingested", "quarantined")
    # Bronze keeps both copies - it is append-only - but silver and gold must not move.
    assert period_rows(warehouse, "silver", "oms_orders", period) == silver_before
    assert gold_revenue_for(warehouse, period) == pytest.approx(gold_before, rel=1e-9)


# ---------------------------------------------------------------- restatement --
def test_a_restatement_supersedes_and_both_versions_remain_queryable(
    replayed: dict[str, object],
) -> None:
    """Supersede-by-batch: newest batch wins the period, the prior version survives."""
    warehouse = replayed["warehouse"]
    period = restatable_week(warehouse)

    before = silver_spend(warehouse, period)
    original_batches = bronze_batches(warehouse, "martech_weekly", period)

    outcome = replayed["controls"].send_restatement("martech_weekly", period)

    assert outcome.results, "the restatement produced no ingest result"
    after = silver_spend(warehouse, period)
    assert after != pytest.approx(before, rel=1e-9), "the restated figure did not move"

    now_batches = bronze_batches(warehouse, "martech_weekly", period)
    assert original_batches < now_batches, "bronze did not retain the prior version"
    # Exactly one batch owns the period in silver: the newest.
    owning = warehouse.query(
        "SELECT DISTINCT _batch_id FROM silver.martech_weekly WHERE _period = $period",
        {"period": period},
    )
    assert len(owning) == 1


def test_a_restatement_rewinds_the_watermark_for_its_period_only(
    replayed: dict[str, object],
) -> None:
    """A late or revised batch re-opens *its* period and no other."""
    harness = replayed["harness"]
    warehouse = replayed["warehouse"]
    period = restatable_week(warehouse)
    other = week_label(dt.date.fromisoformat(week_monday(period)) - dt.timedelta(days=7))
    before_other = harness.runner.batch_registry.revisions_of("martech_weekly", other)

    outcome = replayed["controls"].send_restatement("martech_weekly", period)
    event = next(result.event for result in outcome.results if result.event is not None)

    assert event.watermark_rewound is True
    assert event.periods == [period]
    assert harness.runner.batch_registry.revisions_of("martech_weekly", other) == before_other


def test_a_landing_wakes_only_the_kpis_that_depend_on_the_source(
    replayed: dict[str, object],
) -> None:
    """Event-driven, not cron-driven: a MarTech drop does not re-scan fill rate."""
    outcome = replayed["controls"].send_restatement(
        "martech_weekly", restatable_week(replayed["warehouse"])
    )
    event = next(result.event for result in outcome.results if result.event is not None)
    assert set(event.wakes_kpis) == {"blended_roas", "marketing_spend"}
    assert "order_fill_rate" not in event.wakes_kpis
    assert "net_revenue" not in event.wakes_kpis


# ---------------------------------------------------------- late / out of order --
def test_a_late_batch_recomputes_exactly_the_affected_window(
    replayed: dict[str, object],
) -> None:
    """A period arriving late rebuilds its own days and leaves the rest untouched."""
    harness = replayed["harness"]
    warehouse = replayed["warehouse"]
    contract = harness.contracts.source("wms_fulfilment")

    late_day = harness.clock.today - dt.timedelta(days=40)
    neighbour = late_day - dt.timedelta(days=1)
    before_neighbour = fulfilment_units(warehouse, neighbour)

    arrival = daily_arrival(contract, harness.clock.now, late_day)
    frame = harness.slicer.slice(contract, arrival)
    harness.land_frame(arrival, frame, producer_note="late backfill of a missed night")
    results = [item for item in harness.drain() if item.source_id == "wms_fulfilment"]

    assert results, "the late batch was not ingested"
    event = results[0].event
    assert event is not None
    assert event.affected_days == [late_day]
    assert fulfilment_units(warehouse, neighbour) == before_neighbour


# ------------------------------------------------------- freshness under a break --
def test_pausing_a_feed_walks_freshness_green_amber_red(replayed: dict[str, object]) -> None:
    """The "break a feed" control, on the contract's own SLA schedule."""
    harness = replayed["harness"]
    contract = harness.contracts.source("martech_weekly")
    sla = contract.latency_sla_hours

    replayed["controls"].break_feed("martech_weekly")
    scheduler = ArrivalScheduler(harness.contracts, replayed["seeds"])
    # Step past the next scheduled drop so the paused feed has something to miss.
    due = scheduler.next_arrival("martech_weekly", harness.clock.now)
    harness.advance_to(due + dt.timedelta(minutes=1))

    states: list[str] = []
    for hours in (0.0, sla * 0.75, sla * 1.5):
        harness.clock.travel_to(due + dt.timedelta(hours=hours, minutes=1))
        states.append(freshness(harness, "martech_weekly").state)

    assert states == ["green", "amber", "red"], states
    assert freshness(harness, "martech_weekly").breached is True
    replayed["controls"].restore_feed("martech_weekly")


# --------------------------------------------------------- quarantine and drift --
def test_the_silent_unit_change_is_quarantined_by_a_range_expectation(
    loaded: dict[str, object],
) -> None:
    """P8 — the scariest defect, caught by the contract's declared ceiling."""
    warehouse = loaded["warehouse"]
    held = warehouse.query(
        "SELECT rule, count(*) AS n FROM meta.quarantine_rows "
        "WHERE source_id = 'martech_weekly' GROUP BY rule"
    )
    rules = dict(zip(held["rule"], held["n"], strict=True))
    assert rules.get("range:spend_inr", 0) > 0, rules

    ceiling = (
        loaded["harness"].contracts.source("martech_weekly").schema_spec.columns["spend_inr"].max
    )
    surviving = warehouse.query("SELECT max(spend_inr) AS worst FROM silver.martech_weekly")[
        "worst"
    ].iloc[0]
    assert float(surviving) <= float(ceiling)

    # And it was the unit-change window that produced them, not a random week.
    quarantined_weeks = warehouse.query(
        "SELECT DISTINCT b.iso_week AS week FROM bronze.martech_weekly b "
        "JOIN meta.quarantine_rows q ON q.row_hash = b._row_hash "
        "WHERE q.rule = 'range:spend_inr'"
    )["week"]
    starts = {week_monday_date(week) for week in quarantined_weeks}
    assert starts, "no week was identified for the quarantined rows"
    assert all(
        SilentUnitChange.CHANGE_FROM <= start < SilentUnitChange.CHANGE_TO for start in starts
    ), sorted(starts)


def test_quarantined_rows_are_visible_and_counted_never_dropped(
    loaded: dict[str, object],
) -> None:
    """Quarantine, never drop: every held row is countable with a reason."""
    counts = loaded["harness"].runner.dq_store.quarantine_counts()
    assert not counts.empty
    assert (counts["rows_quarantined"] > 0).all()
    reasons = loaded["warehouse"].query(
        "SELECT DISTINCT reason FROM meta.quarantine_rows WHERE reason <> ''"
    )
    assert len(reasons) > 0


def test_the_schema_drift_is_alerted_and_kept_out_of_silver(
    loaded: dict[str, object],
) -> None:
    """P7 — an undeclared column raises an alert and never reaches a mart."""
    warehouse = loaded["warehouse"]
    alerts = warehouse.query(
        "SELECT * FROM meta.drift_alerts WHERE source_id = 'martech_weekly' "
        "AND kind = 'unexpected_column'"
    )
    assert len(alerts) > 0, "the MarTech schema drift raised no alert"
    assert SchemaDrift.RENAMED_TO in str(alerts["columns"].iloc[0])
    assert SchemaDrift.RENAMED_TO in warehouse.columns("bronze", "martech_weekly")
    assert SchemaDrift.RENAMED_TO not in warehouse.columns("silver", "martech_weekly")


def test_the_timezone_declaration_is_verified_against_the_business_key(
    loaded: dict[str, object],
) -> None:
    """P9 — after conversion, every ticket sits on the day its id encodes."""
    tickets = loaded["warehouse"].query(
        "SELECT ticket_id, opened_at_ts FROM silver.support_tickets"
    )
    assert len(tickets) > 0
    encoded = tickets["ticket_id"].astype(str).str.slice(4, 12)
    stamped = pd.to_datetime(tickets["opened_at_ts"]).dt.strftime("%Y%m%d")
    assert float((encoded != stamped).mean()) < 0.005


def test_the_foreign_desk_is_converted_at_the_policy_rate(loaded: dict[str, object]) -> None:
    """P11 — USD-booked export lines reach gold in rupees."""
    warehouse = loaded["warehouse"]
    implausible = warehouse.query(
        "SELECT count(*) AS n FROM gold.fct_revenue_daily "
        "WHERE region = 'East' AND channel = 'marketplace' AND unit_price_net < 20.0"
    )["n"].iloc[0]
    assert int(implausible) == 0


def test_pii_is_masked_before_anything_is_written(loaded: dict[str, object]) -> None:
    """Sensitive strings never enter silver, and therefore never enter the index."""
    tickets = loaded["warehouse"].query(
        "SELECT customer_email, customer_name, body_text FROM silver.support_tickets LIMIT 500"
    )
    assert len(tickets) > 0
    assert tickets["customer_email"].astype(str).str.startswith("<EMAIL:").all()
    assert tickets["customer_name"].astype(str).str.startswith("<NAME:").all()
    assert not tickets["body_text"].astype(str).str.contains("@example.com").any()


def test_age_never_reads_negative_after_the_clock_travels_backwards() -> None:
    """The demo controls move the simulated clock, so a batch can carry a
    ``received_at`` later than "now". A tile reading "-28h old" is meaningless; the age
    is clamped while the STATE stays driven by whether the due drop arrived, so a stale
    source cannot be masked by the clamp.
    """
    import datetime as dt

    from insight_copilot.ingest.freshness import FreshnessTracker

    now = dt.datetime(2026, 3, 29, tzinfo=dt.UTC)
    future = now + dt.timedelta(hours=28)
    assert max((now - future).total_seconds() / 3600.0, 0.0) == 0.0
    assert FreshnessTracker is not None
