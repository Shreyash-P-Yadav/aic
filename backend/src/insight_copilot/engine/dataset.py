"""How the engine gets data. **Through the contract compiler, never around it.**

The design rule is stated once in the data-layer document and holds everywhere: the
analytical engine never reads bronze or silver, and it reads gold *through the
contract compiler*, so entitlements and definitions apply uniformly whether the caller
is a scheduled scan, a persona narrative, or an analyst's ad-hoc question.

The driver panel is the one object that is not a KPI mart, so it cannot go through the
compiler — there is no contract whose measure it is. It is read here instead, with the
caller's session row filter applied by the same rule the compiler would use, and it
carries no measure any contract masks.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.engine.series import Series
from insight_copilot.errors import ContractError
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.security.compiler import ContractSQLCompiler
from insight_copilot.security.executor import QueryExecutor
from insight_copilot.security.identity import SessionContext
from insight_copilot.security.query import FilterClause, QueryRequest

PANEL_TABLE = "gold.driver_panel"
CUBE_TABLE = "gold.cube_revenue"

REGION_BINDING = "user_region"
"""The session binding a region-scoped role supplies. The panel reader applies it for
the same reason the compiler does: an RSM must not see another region's drivers."""


@dataclass
class EngineDataset:
    """Compiler-mediated access to the marts, plus the pre-joined driver panel."""

    warehouse: Warehouse
    registry: ContractRegistry
    compiler: ContractSQLCompiler
    executor: QueryExecutor

    # ------------------------------------------------------------ kpi access --
    def kpi_frame(
        self,
        contract_id: str,
        session: SessionContext,
        *,
        grain: list[str],
        measures: list[str] | None = None,
        filters: list[FilterClause] | None = None,
    ) -> pd.DataFrame:
        """Any KPI at any permitted grain, compiled and audited."""
        request = QueryRequest(
            contract_id=contract_id,
            grain=grain,
            measures=measures or [],
            filters=filters or [],
            order_by=grain,
        )
        return self.executor.run(self.compiler.compile(request, session), session)

    def kpi_series(
        self,
        contract_id: str,
        session: SessionContext,
        *,
        filters: list[FilterClause] | None = None,
        date_column: str = "date",
    ) -> Series:
        """A KPI as a gap-free daily series, ready for a baseline."""
        frame = self.kpi_frame(contract_id, session, grain=[date_column], filters=filters)
        contract = self.registry.kpi(contract_id)
        # A ratio has no meaningful zero-fill: an absent day is unknown, not nought.
        fill = None if contract.definition.ratio_of is not None else 0.0
        return Series.from_frame(
            frame, date_column=date_column, value_column=contract_id, fill=fill
        )

    # ---------------------------------------------------------------- panel --
    def driver_panel(
        self, session: SessionContext, *, start: dt.date | None = None, end: dt.date | None = None
    ) -> pd.DataFrame:
        """The pre-joined daily driver panel, row-filtered for the caller."""
        if not self.warehouse.exists("gold", "driver_panel"):
            raise ContractError("gold.driver_panel has not been built; run the ingestion first")
        predicates: list[str] = []
        parameters: dict[str, object] = {}
        region = session.bindings.get(REGION_BINDING)
        if region is not None:
            predicates.append("region = $user_region")
            parameters["user_region"] = region
        if start is not None:
            predicates.append("date >= $start")
            parameters["start"] = start
        if end is not None:
            predicates.append("date <= $end")
            parameters["end"] = end
        where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
        return self.warehouse.query(
            f"SELECT * FROM {PANEL_TABLE}{where} ORDER BY date, region", parameters
        )

    def national_panel(
        self, session: SessionContext, *, start: dt.date | None = None, end: dt.date | None = None
    ) -> pd.DataFrame:
        """The driver panel aggregated to one row per day.

        Revenue-weighted where a ratio is being averaged: the mean of daily fill rates
        across regions is not the national fill rate, and the difference is exactly the
        mix effect the ladder's second rung exists to measure.
        """
        panel = self.driver_panel(session, start=start, end=end)
        if panel.empty:
            return panel
        weight = panel["net_revenue_inr"].clip(lower=0.0)
        weighted = panel.assign(
            _w=weight,
            _fill=panel["fill_rate_pct"] * weight,
            _asp=panel["asp_inr"] * weight,
            _discount=panel["discount_depth_pct"] * weight,
        )
        grouped = weighted.groupby("date", observed=True).agg(
            net_revenue_inr=("net_revenue_inr", "sum"),
            units=("units", "sum"),
            daily_spend_inr=("daily_spend_inr", "sum"),
            daily_attributed_inr=("daily_attributed_inr", "sum"),
            rainfall_mm=("rainfall_mm", "mean"),
            temp_max_c=("temp_max_c", "mean"),
            is_holiday=("is_holiday", "max"),
            _w=("_w", "sum"),
            _fill=("_fill", "sum"),
            _asp=("_asp", "sum"),
            _discount=("_discount", "sum"),
        )
        for name in ("fill", "asp", "discount"):
            grouped[f"{name}_weighted"] = grouped[f"_{name}"] / grouped["_w"].replace(0.0, pd.NA)
        grouped = grouped.rename(
            columns={
                "fill_weighted": "fill_rate_pct",
                "asp_weighted": "asp_inr",
                "discount_weighted": "discount_depth_pct",
            }
        ).drop(columns=["_w", "_fill", "_asp", "_discount"])
        return grouped.reset_index()

    def cube(self, session: SessionContext, *, start: dt.date, end: dt.date) -> pd.DataFrame:
        """The dimensional cube over a window — Adtributor's input."""
        predicates = ["date BETWEEN $start AND $end"]
        parameters: dict[str, object] = {"start": start, "end": end}
        region = session.bindings.get(REGION_BINDING)
        if region is not None:
            predicates.append("region = $user_region")
            parameters["user_region"] = region
        return self.warehouse.query(
            f"SELECT * FROM {CUBE_TABLE} WHERE {' AND '.join(predicates)}", parameters
        )
