"""Helpers for the P5 gate.

Kept out of ``test_p5_ingest.py`` so that file stays inside the four-hundred-line
limit the build standard sets, and named without a ``test_`` prefix so pytest does not
try to collect it.
"""

from __future__ import annotations

import datetime as dt

from insight_copilot.harness.periods import day_label
from insight_copilot.harness.scheduler import manual_arrival
from insight_copilot.ingest.gold import REVENUE_MART


def latest_landed(harness, source_id: str):  # type: ignore[no-untyped-def]
    """The most recently landed batch for a source, read back off the disk.

    A fresh watcher rather than the harness's own: the harness's watcher has already
    offered these files and remembers doing so, and this helper needs the file itself,
    not the next thing to ingest.
    """
    from insight_copilot.harness.landing import SourceWatcher

    landed = [
        item
        for item in SourceWatcher(harness.landing).poll(harness.clock.now)
        if item.source_id == source_id
    ]
    assert landed, f"no landed batch for {source_id}"
    return landed[-1]


def rearrival(batch, moment):  # type: ignore[no-untyped-def]
    """A fresh arrival re-delivering an existing batch's periods at ``moment``."""
    return manual_arrival(batch.source_id, tuple(batch.manifest.covers.periods), moment)


def daily_arrival(contract, moment, day):  # type: ignore[no-untyped-def]
    """An arrival covering exactly one past day — a late nightly extract."""
    return manual_arrival(contract.source_id, (day_label(day),), moment)


def expected_new_id(results, batch):  # type: ignore[no-untyped-def]
    """The batch id of the re-delivery, which differs from the original's."""
    for result in results:
        if result.source_id == batch.source_id and result.batch_id != batch.batch_id:
            return result.batch_id
    return batch.batch_id


def period_rows(warehouse, schema, table, period) -> int:  # type: ignore[no-untyped-def]
    return int(
        warehouse.query(
            f"SELECT count(*) AS n FROM {schema}.{table} WHERE _period = $period",
            {"period": period},
        )["n"].iloc[0]
    )


def gold_revenue_for(warehouse, period) -> float:  # type: ignore[no-untyped-def]
    return float(
        warehouse.query(
            "SELECT coalesce(sum(units * unit_price_net) - sum(returns_value), 0.0) AS revenue "
            f"FROM gold.{REVENUE_MART} WHERE date = $day",
            {"day": dt.date.fromisoformat(period)},
        )["revenue"].iloc[0]
    )


def fulfilment_units(warehouse, day) -> float:  # type: ignore[no-untyped-def]
    return float(
        warehouse.query(
            "SELECT coalesce(sum(units_shipped_ok), 0) AS n "
            "FROM gold.fct_fulfilment_daily WHERE date = $day",
            {"day": day},
        )["n"].iloc[0]
    )


def silver_spend(warehouse, period) -> float:  # type: ignore[no-untyped-def]
    return float(
        warehouse.query(
            "SELECT coalesce(sum(attributed_revenue_inr), 0.0) AS total "
            "FROM silver.martech_weekly WHERE _period = $period",
            {"period": period},
        )["total"].iloc[0]
    )


def bronze_batches(warehouse, table, period) -> int:  # type: ignore[no-untyped-def]
    return int(
        warehouse.query(
            f"SELECT count(DISTINCT _batch_id) AS n FROM bronze.{table} WHERE _period = $period",
            {"period": period},
        )["n"].iloc[0]
    )


def restatable_week(warehouse) -> str:  # type: ignore[no-untyped-def]
    """A MarTech week that has landed and carries rows worth revising."""
    weeks = warehouse.query(
        "SELECT _period AS week, sum(attributed_revenue_inr) AS total "
        "FROM silver.martech_weekly GROUP BY 1 HAVING sum(attributed_revenue_inr) > 0 "
        "ORDER BY 1 DESC LIMIT 3"
    )
    assert not weeks.empty, "no MarTech week available to restate"
    return str(weeks["week"].iloc[1])


def freshness(harness, source_id):  # type: ignore[no-untyped-def]
    return next(status for status in harness.freshness() if status.source_id == source_id)


def week_monday(period: str) -> str:
    return week_monday_date(period).isoformat()


def week_monday_date(period: str) -> dt.date:
    year, _, week = str(period).partition("-W")
    return dt.date.fromisocalendar(int(year), int(week), 1)
