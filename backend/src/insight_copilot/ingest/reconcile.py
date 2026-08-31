"""Cross-source reconciliation, as declared on the source contracts.

Every check here is a disagreement the design *expects*. Two systems counting the same
thing differently is normal — the OMS books an order at midnight IST and the WMS ships
it two days later; the ad platform claims view-through revenue the order book never
sees. Living with that gap is the point.

What is not normal is the gap **exceeding the contract's tolerance**, and that is what
this module measures. A breach on a check whose ``on_breach`` is ``block_attribution``
is a hard gate: the engine abstains rather than attributing a movement to a driver
whose two witnesses disagree by more than the business agreed they may. That is
Scenario B.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.contracts.source_models import ReconciliationCheck
from insight_copilot.ingest.models import ReconciliationResult
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

MIN_DENOMINATOR = 1.0
"""Guards the percentage when a window's right-hand total is zero or near it. Below
one unit or one rupee a percentage difference carries no information."""


@dataclass(frozen=True)
class MeasurePair:
    """How to measure one declared check on both sides, per window."""

    left_sql: str
    right_sql: str
    requires: tuple[tuple[str, str], ...]
    note: str


_OMS_UNITS_DAILY = (
    "SELECT date AS window_key, sum(units) AS value FROM gold.fct_revenue_daily GROUP BY 1"
)
_WMS_UNITS_DAILY = (
    "SELECT date AS window_key, sum(units_ordered) AS value "
    "FROM gold.fct_fulfilment_daily GROUP BY 1"
)
_MARTECH_ATTRIBUTED_WEEKLY = (
    "SELECT iso_week AS window_key, sum(attributed_revenue_inr) AS value "
    "FROM gold.fct_marketing_weekly GROUP BY 1"
)
_OMS_LINKED_WEEKLY = (
    "SELECT iso_week AS window_key, sum(units * unit_price_net) AS value "
    "FROM gold.fct_revenue_daily GROUP BY 1"
)
_INVENTORY_SNAPSHOT_DAILY = (
    "SELECT date AS window_key, sum(on_hand_units) AS value "
    "FROM silver.inventory_snapshots GROUP BY 1"
)
_INVENTORY_IMPLIED_DAILY = """
SELECT window_key, value FROM (
    SELECT s.date AS window_key,
           lag(s.on_hand) OVER (ORDER BY s.date) - coalesce(f.shipped, 0) AS value
    FROM (
        SELECT date, sum(on_hand_units) AS on_hand FROM silver.inventory_snapshots GROUP BY 1
    ) s
    LEFT JOIN (
        SELECT date, sum(units_shipped_ok) AS shipped FROM gold.fct_fulfilment_daily GROUP BY 1
    ) f ON f.date = s.date
) WHERE value IS NOT NULL
"""

MEASURE_PAIRS: dict[tuple[str, str, str], MeasurePair] = {
    ("oms_orders", "wms_fulfilment", "units"): MeasurePair(
        left_sql=_OMS_UNITS_DAILY,
        right_sql=_WMS_UNITS_DAILY,
        requires=(("gold", "fct_revenue_daily"), ("gold", "fct_fulfilment_daily")),
        note="midnight cut-off, partial shipments, T+2 extract view",
    ),
    ("wms_fulfilment", "oms_orders", "units_ordered"): MeasurePair(
        left_sql=_WMS_UNITS_DAILY,
        right_sql=_OMS_UNITS_DAILY,
        requires=(("gold", "fct_fulfilment_daily"), ("gold", "fct_revenue_daily")),
        note="the same disagreement seen from the warehouse side",
    ),
    ("martech_weekly", "oms_orders", "attributed_revenue_inr"): MeasurePair(
        left_sql=_MARTECH_ATTRIBUTED_WEEKLY,
        right_sql=_OMS_LINKED_WEEKLY,
        requires=(("gold", "fct_marketing_weekly"), ("gold", "fct_revenue_daily")),
        note="attribution windows, view-through and cross-device journeys",
    ),
    ("inventory_snapshots", "wms_fulfilment", "on_hand_units"): MeasurePair(
        left_sql=_INVENTORY_SNAPSHOT_DAILY,
        right_sql=_INVENTORY_IMPLIED_DAILY,
        requires=(("silver", "inventory_snapshots"), ("gold", "fct_fulfilment_daily")),
        note="a snapshot is a moment; the implied position is a reconstruction; "
        "shrinkage sits between them",
    ),
}
"""The measurable form of each contract-declared check. It lives in code rather than
in YAML because it is an *expression* over two schemas, not a threshold — the governed
half (tolerance, window, breach action) stays on the contract."""


class ReconciliationRunner:
    """Measures every contract-declared cross-source check against the warehouse."""

    def __init__(self, warehouse: Warehouse, registry: ContractRegistry) -> None:
        self._warehouse = warehouse
        self._registry = registry

    def run_all(self) -> list[ReconciliationResult]:
        """Every declared check on every source, skipping any whose marts are absent."""
        results: list[ReconciliationResult] = []
        for source_id in self._registry.source_ids:
            for check in self._registry.source(source_id).reconciliation:
                result = self.run(source_id, check)
                if result is not None:
                    results.append(result)
        return results

    def run(self, source_id: str, check: ReconciliationCheck) -> ReconciliationResult | None:
        """Measure one check. Returns ``None`` when its inputs have not landed yet."""
        pair = MEASURE_PAIRS.get((source_id, check.against, check.measure))
        if pair is None:
            logger.warning(
                "reconcile.unmeasurable",
                left=source_id,
                right=check.against,
                measure=check.measure,
            )
            return None
        if not all(self._warehouse.exists(schema, table) for schema, table in pair.requires):
            return None

        left = self._warehouse.query(pair.left_sql).set_index("window_key")["value"]
        right = self._warehouse.query(pair.right_sql).set_index("window_key")["value"]
        joined = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
        joined = joined.loc[joined["right"].abs() > MIN_DENOMINATOR]
        if joined.empty:
            return None

        delta_pct = (100.0 * (joined["left"] - joined["right"]) / joined["right"]).abs()
        median = float(delta_pct.median())
        worst = float(delta_pct.max())
        breached = median > check.tolerance_pct
        result = ReconciliationResult(
            left=source_id,
            right=check.against,
            measure=check.measure,
            window=check.window,
            periods_checked=len(joined),
            median_abs_delta_pct=median,
            max_abs_delta_pct=worst,
            tolerance_pct=check.tolerance_pct,
            breached=breached,
            on_breach=check.on_breach,
            detail=(
                f"{source_id} vs {check.against} on {check.measure}: median "
                f"{median:.2f}% against a {check.tolerance_pct:.1f}% tolerance "
                f"over {len(joined)} {check.window}(s) — {pair.note}"
            ),
        )
        if breached:
            logger.info(
                "reconcile.breach",
                left=source_id,
                right=check.against,
                median_pct=median,
                tolerance_pct=check.tolerance_pct,
                on_breach=check.on_breach,
            )
        return result

    def persist(self, results: list[ReconciliationResult]) -> None:
        """Replace the reconciliation table. The evidence drawer reads it."""
        frame = pd.DataFrame([result.model_dump(mode="json") for result in results])
        self._warehouse.replace("meta", "reconciliation", frame)
