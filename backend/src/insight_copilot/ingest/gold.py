"""Gold — the contract-grain marts and the dimensional cube.

**The analytical engine never reads bronze or silver.** It reads gold *through the
contract compiler*, so entitlements and definitions apply uniformly whether the caller
is a scheduled scan, a persona narrative, or an analyst's ad-hoc question. Each mart
is named by a KPI contract's own ``source_view``, and each carries exactly the columns
that contract's ``measure_sql`` and ``derived_submetrics`` reference — a mart that
drifts from its contract fails the first query rather than the demo.

Marts are rebuilt **for the affected days only**. A batch covering one Tuesday deletes
and recomputes one Tuesday. That is the whole point of tracking watermarks per period.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

REVENUE_MART = "fct_revenue_daily"
FULFILMENT_MART = "fct_fulfilment_daily"
MARKETING_MART = "fct_marketing_weekly"
REVENUE_CUBE = "cube_revenue"

UNKNOWN_MEMBER = "UNKNOWN"
"""The bucket a dimension value lands in when the master does not know it yet. It is a
member, not a null: Scenario C's launch sells for nine days before the PIM classifies
it, and those sales must still appear in the national total."""

_PIM_LATEST = """
SELECT product_sku, valid_from, category, unit_cost, product_name
FROM (
    SELECT *, row_number() OVER (
        PARTITION BY product_sku, valid_from ORDER BY _received_at DESC
    ) AS _rank
    FROM silver.pim_products
) WHERE _rank = 1
"""
"""The product master as a slowly-changing dimension: one row per key per validity
start, newest delivery winning. An ASOF join against this is what gives every order
line the master as it stood *on that day* rather than as it stands now."""

_REVENUE_SELECT = f"""
SELECT
    o.date                                   AS date,
    o.iso_week                               AS iso_week,
    o.product_sku                            AS product_sku,
    coalesce(p.category, '{UNKNOWN_MEMBER}')  AS category,
    o.region                                 AS region,
    o.channel                                AS channel,
    coalesce(o.customer_segment, '{UNKNOWN_MEMBER}') AS customer_segment,
    o.units                                  AS units,
    o.unit_price_net                         AS unit_price_net,
    o.list_price                             AS list_price,
    p.unit_cost                              AS unit_cost,
    o.returns_value                          AS returns_value,
    o.cancelled_units                        AS cancelled_units,
    o._batch_id                              AS _batch_id
FROM (SELECT * FROM silver.oms_orders WHERE date BETWEEN $lo AND $hi) o
ASOF LEFT JOIN ({_PIM_LATEST}) p
    ON o.product_sku = p.product_sku AND o.date >= p.valid_from
"""

_FULFILMENT_SELECT = f"""
SELECT
    w.date                                   AS date,
    w.iso_week                               AS iso_week,
    w.warehouse                              AS warehouse,
    w.region                                 AS region,
    w.product_sku                            AS product_sku,
    coalesce(p.category, '{UNKNOWN_MEMBER}')  AS category,
    w.units_ordered                          AS units_ordered,
    w.units_shipped_ok                       AS units_shipped_ok,
    w.units_short                            AS units_short,
    w.inbound_delay_days                     AS inbound_delay_days,
    w._batch_id                              AS _batch_id
FROM (SELECT * FROM silver.wms_fulfilment WHERE date BETWEEN $lo AND $hi) w
ASOF LEFT JOIN ({_PIM_LATEST}) p
    ON w.product_sku = p.product_sku AND w.date >= p.valid_from
"""

_MARKETING_SELECT = f"""
SELECT
    m.iso_week                               AS iso_week,
    m.date                                   AS date,
    m.campaign_id                            AS campaign_id,
    m.channel                                AS channel,
    coalesce(m.region, '{UNKNOWN_MEMBER}')    AS region,
    m.spend_inr                              AS spend_inr,
    m.impressions                            AS impressions,
    m.clicks                                 AS clicks,
    m.attributed_revenue_inr                 AS attributed_revenue_inr,
    m._batch_id                              AS _batch_id
FROM (SELECT * FROM silver.martech_weekly WHERE date BETWEEN $lo AND $hi) m
"""

_CUBE_SELECT = """
SELECT
    date, iso_week, category, region, channel, customer_segment,
    sum(units)                                       AS units,
    sum(units * unit_price_net) - sum(returns_value) AS net_revenue_inr,
    sum(units * unit_price_net)                      AS gross_revenue_inr,
    sum(units * coalesce(unit_cost, 0.0))            AS cost_inr,
    sum(units * list_price)                          AS list_value_inr,
    sum(returns_value)                               AS returns_inr
FROM gold.fct_revenue_daily
WHERE date BETWEEN $lo AND $hi
GROUP BY date, iso_week, category, region, channel, customer_segment
"""


@dataclass(frozen=True)
class MartSpec:
    """One mart: what it is called, how it is built, and what it needs to exist."""

    table: str
    select: str
    key_column: str
    requires: tuple[tuple[str, str], ...]
    """``(schema, table)`` pairs that must exist before this mart can be built. A mart
    whose sources have not landed yet is skipped, not failed: during a cold start the
    OMS lands hours before the PIM, and a pipeline that crashed on that would never
    survive its own first day."""


MARTS: tuple[MartSpec, ...] = (
    MartSpec(
        table=REVENUE_MART,
        select=_REVENUE_SELECT,
        key_column="date",
        requires=(("silver", "oms_orders"), ("silver", "pim_products")),
    ),
    MartSpec(
        table=FULFILMENT_MART,
        select=_FULFILMENT_SELECT,
        key_column="date",
        requires=(("silver", "wms_fulfilment"), ("silver", "pim_products")),
    ),
    MartSpec(
        table=MARKETING_MART,
        select=_MARKETING_SELECT,
        key_column="iso_week",
        requires=(("silver", "martech_weekly"),),
    ),
    MartSpec(
        table=REVENUE_CUBE,
        select=_CUBE_SELECT,
        key_column="date",
        requires=(("gold", REVENUE_MART),),
    ),
)
"""Build order matters: the cube reads the revenue mart, so it comes after it."""


@dataclass(frozen=True)
class GoldRebuild:
    """Rows written per mart by one rebuild, and which marts were skipped."""

    days: int
    weeks: int
    rows: dict[str, int]
    skipped: tuple[str, ...] = ()


class GoldBuilder:
    """Rebuilds the contract marts and the cube for a window of days."""

    def __init__(self, warehouse: Warehouse) -> None:
        self._warehouse = warehouse

    def rebuild(self, days: list[dt.date]) -> GoldRebuild:
        """Recompute every buildable mart for exactly these days. Idempotent."""
        if not days:
            return GoldRebuild(days=0, weeks=0, rows={})
        weeks = sorted({_week_of(day) for day in days})
        # The exact key list decides *which* rows are rebuilt; the date range is a
        # redundant bound that DuckDB can push down into the silver scan. Without it
        # every daily rebuild reads the whole thirty-six-month table, which turns a
        # ninety-day replay into a quadratic one.
        bounds: dict[str, object] = {
            "lo": _week_start(weeks[0]) if weeks else min(days),
            "hi": max(max(days), _week_end(weeks[-1])),
        }
        rows: dict[str, int] = {}
        skipped: list[str] = []
        for spec in MARTS:
            if not all(self._warehouse.exists(schema, table) for schema, table in spec.requires):
                skipped.append(spec.table)
                continue
            keys: list[object] = list(weeks) if spec.key_column == "iso_week" else list(days)
            rows[spec.table] = self._rebuild(spec, {"keys": keys, **bounds})
        logger.info("gold.rebuilt", days=len(days), weeks=len(weeks), rows=rows, skipped=skipped)
        return GoldRebuild(days=len(days), weeks=len(weeks), rows=rows, skipped=tuple(skipped))

    def _rebuild(self, spec: MartSpec, parameters: dict[str, object]) -> int:
        """The delete-and-insert that keeps a rebuild scoped to its window.

        The filter is a bound list parameter, never interpolated text: values in this
        system are always bound, ingestion included.
        """
        predicate = f"list_contains($keys, {spec.key_column})"
        scoped = f"SELECT * FROM ({spec.select}) WHERE {predicate}"
        if self._warehouse.exists("gold", spec.table):
            self._warehouse.delete_where(
                "gold", spec.table, f"date BETWEEN $lo AND $hi AND {predicate}", parameters
            )
            before = self._warehouse.row_count("gold", spec.table)
            self._warehouse.execute(f"INSERT INTO gold.{spec.table} {scoped}", parameters)
            return self._warehouse.row_count("gold", spec.table) - before
        self._warehouse.execute(f"CREATE TABLE gold.{spec.table} AS {scoped}", parameters)
        return self._warehouse.row_count("gold", spec.table)


def _week_of(day: dt.date) -> str:
    """ISO-week label for a day, as the weekly mart keys itself."""
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _week_start(label: str) -> dt.date:
    """Monday of an ISO-week label — the low end of a weekly rebuild's date range."""
    year, _, week = label.partition("-W")
    return dt.date.fromisocalendar(int(year), int(week), 1)


def _week_end(label: str) -> dt.date:
    """Sunday of an ISO-week label."""
    return _week_start(label) + dt.timedelta(days=6)
