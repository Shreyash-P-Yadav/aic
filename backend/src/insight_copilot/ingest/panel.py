"""The calendar spine and the pre-joined driver panel.

Two gold objects that are not KPI marts:

* ``gold.dim_calendar`` — **every date exists, gaps explicit.** A spine built from the
  configured horizon rather than from the data, so a day with no sales is a row of
  zeros rather than a missing row. Every time-series method downstream depends on
  this: a gap silently closed by a join is how a seven-day seasonal period turns into
  a six-day one and every seasonal decomposition quietly becomes wrong.
* ``gold.driver_panel`` — one row per date and region carrying the KPI and every
  exogenous driver aligned to it. The econometrics in P6 read this and nothing else,
  so the joins happen once, at load, and not inside a regression loop.

Both are rebuilt for the affected window only, like every other gold object.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

CALENDAR_TABLE = "dim_calendar"
PANEL_TABLE = "driver_panel"

FISCAL_YEAR_START_MONTH = 4
"""Meridian reports on an April-March fiscal year, as most Indian companies do. The
KPI contracts declare ``calendar: fiscal_apr_mar`` and this is where that becomes a
column something can group by."""

DAYS_PER_WEEK = 7.0
"""Weekly media spend is spread evenly across its week to align with a daily KPI. Even
spreading is the honest default: the feed reports a week and does not say which days
inside it carried the impressions, so any other allocation would be an invention."""


@dataclass(frozen=True)
class PanelRebuild:
    """Rows written by one spine/panel rebuild."""

    calendar_rows: int
    panel_rows: int


class PanelBuilder:
    """Builds the calendar spine and the driver panel."""

    def __init__(self, warehouse: Warehouse) -> None:
        self._warehouse = warehouse

    # -------------------------------------------------------------- calendar --
    def build_calendar(self, start: dt.date, end: dt.date) -> int:
        """Materialise the spine over the whole horizon. Cheap; built once per run."""
        days = pd.date_range(start, end, freq="D")
        holidays = self._holidays()
        frame = pd.DataFrame(
            {
                "date": [stamp.date() for stamp in days],
                "iso_week": [f"{s.isocalendar()[0]}-W{s.isocalendar()[1]:02d}" for s in days],
                "day_of_week": days.dayofweek.astype("int64"),
                "day_of_year": days.dayofyear.astype("int64"),
                "month": days.month.astype("int64"),
                "fiscal_year": [_fiscal_year(stamp.date()) for stamp in days],
                "is_month_end": days.is_month_end,
            }
        )
        frame["is_holiday"] = frame["date"].isin(holidays.keys())
        frame["holiday_name"] = frame["date"].map(holidays).fillna("")
        rows = self._warehouse.replace("gold", CALENDAR_TABLE, frame)
        logger.info("panel.calendar_built", rows=rows, start=str(start), end=str(end))
        return rows

    def _holidays(self) -> dict[dt.date, str]:
        """Demand-relevant holidays, from the ingested calendar feed."""
        if not self._warehouse.exists("silver", "holiday_calendar"):
            return {}
        found = self._warehouse.query(
            "SELECT DISTINCT holiday_date, holiday_name FROM silver.holiday_calendar "
            "WHERE demand_relevant"
        )
        holidays: dict[dt.date, str] = {}
        for row in found.itertuples():
            day = row.holiday_date
            if pd.isna(day) or not isinstance(day, dt.date):
                continue
            holidays[day] = str(row.holiday_name)
        return holidays

    # ----------------------------------------------------------------- panel --
    def rebuild_panel(self, days: list[dt.date]) -> int:
        """Rebuild the driver panel for exactly these days."""
        if not days or not self._warehouse.exists("gold", "fct_revenue_daily"):
            return 0
        # ``lo``/``hi`` are a redundant range bound the planner can push into the mart
        # scans; ``keys`` is what actually decides which rows are rebuilt.
        parameters: dict[str, object] = {"keys": list(days), "lo": min(days), "hi": max(days)}
        predicate = "list_contains($keys, date)"
        scoped = f"SELECT * FROM ({self._panel_sql()}) WHERE {predicate}"
        if self._warehouse.exists("gold", PANEL_TABLE):
            self._warehouse.delete_where(
                "gold", PANEL_TABLE, f"date BETWEEN $lo AND $hi AND {predicate}", parameters
            )
            before = self._warehouse.row_count("gold", PANEL_TABLE)
            self._warehouse.execute(f"INSERT INTO gold.{PANEL_TABLE} {scoped}", parameters)
            return self._warehouse.row_count("gold", PANEL_TABLE) - before
        self._warehouse.execute(f"CREATE TABLE gold.{PANEL_TABLE} AS {scoped}", parameters)
        return self._warehouse.row_count("gold", PANEL_TABLE)

    def _panel_sql(self) -> str:
        """The pre-joined panel. Optional feeds join as ``NULL`` until they land."""
        fulfilment = (
            """
            LEFT JOIN (
                SELECT date, region,
                       sum(units_shipped_ok) AS units_shipped_ok,
                       sum(units_ordered)    AS units_ordered
                FROM gold.fct_fulfilment_daily WHERE date BETWEEN $lo AND $hi GROUP BY date, region
            ) f ON f.date = r.date AND f.region = r.region
            """
            if self._warehouse.exists("gold", "fct_fulfilment_daily")
            else "LEFT JOIN (SELECT NULL AS date, NULL AS region, "
            "NULL AS units_shipped_ok, NULL AS units_ordered) f ON false"
        )
        marketing = (
            f"""
            LEFT JOIN (
                SELECT iso_week, region,
                       sum(spend_inr) / {DAYS_PER_WEEK}               AS daily_spend_inr,
                       sum(attributed_revenue_inr) / {DAYS_PER_WEEK}  AS daily_attributed_inr
                FROM gold.fct_marketing_weekly WHERE date BETWEEN $lo AND $hi
                GROUP BY iso_week, region
            ) m ON m.iso_week = r.iso_week AND m.region = r.region
            """
            if self._warehouse.exists("gold", "fct_marketing_weekly")
            else "LEFT JOIN (SELECT NULL AS iso_week, NULL AS region, "
            "NULL AS daily_spend_inr, NULL AS daily_attributed_inr) m ON false"
        )
        weather = (
            """
            LEFT JOIN (
                SELECT date, region, avg(temp_max_c) AS temp_max_c,
                       avg(rainfall_mm) AS rainfall_mm
                FROM silver.weather_daily WHERE date BETWEEN $lo AND $hi GROUP BY date, region
            ) w ON w.date = r.date AND w.region = r.region
            """
            if self._warehouse.exists("silver", "weather_daily")
            else "LEFT JOIN (SELECT NULL AS date, NULL AS region, NULL AS temp_max_c, "
            "NULL AS rainfall_mm) w ON false"
        )
        calendar = (
            "LEFT JOIN (SELECT * FROM gold.dim_calendar WHERE date BETWEEN $lo AND $hi) c "
            "ON c.date = r.date"
            if self._warehouse.exists("gold", CALENDAR_TABLE)
            else "LEFT JOIN (SELECT NULL AS date, false AS is_holiday, '' AS holiday_name) "
            "c ON false"
        )
        return f"""
        SELECT
            r.date, r.region, r.iso_week,
            r.net_revenue_inr, r.units,
            r.gross_revenue_inr / nullif(r.units, 0)              AS asp_inr,
            100.0 * r.list_discount_inr / nullif(r.list_value_inr, 0) AS discount_depth_pct,
            100.0 * f.units_shipped_ok / nullif(f.units_ordered, 0)   AS fill_rate_pct,
            m.daily_spend_inr, m.daily_attributed_inr,
            w.temp_max_c, w.rainfall_mm,
            coalesce(c.is_holiday, false) AS is_holiday,
            coalesce(c.holiday_name, '')  AS holiday_name
        FROM (
            SELECT date, region, iso_week,
                   sum(units)                                       AS units,
                   sum(units * unit_price_net) - sum(returns_value)  AS net_revenue_inr,
                   sum(units * unit_price_net)                       AS gross_revenue_inr,
                   sum(units * list_price)                           AS list_value_inr,
                   sum(units * (list_price - unit_price_net))        AS list_discount_inr
            FROM gold.fct_revenue_daily WHERE date BETWEEN $lo AND $hi
            GROUP BY date, region, iso_week
        ) r
        {fulfilment}
        {marketing}
        {weather}
        {calendar}
        """


def _fiscal_year(day: dt.date) -> str:
    """``FY2026`` covers April 2025 to March 2026, the Indian convention."""
    year = day.year if day.month >= FISCAL_YEAR_START_MONTH else day.year - 1
    return f"FY{year + 1}"
