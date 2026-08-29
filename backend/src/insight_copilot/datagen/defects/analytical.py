"""P18-P25 — the analytical traps.

These do not corrupt the data; they make naive analysis wrong. Every one of them is
planted because an engine that survives it is demonstrably better than one that was
never tested — and because each is a place where a confident wrong answer is easy.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

import numpy as np
import pandas as pd

from insight_copilot.datagen.defects.base import DefectEvidence, DefectInjector
from insight_copilot.datagen.defects.simpson import SimpsonsParadox
from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames


def _quarantined_weeks(index: pd.Index) -> pd.Series:
    """Weeks the DQ layer would have quarantined before any analysis saw them.

    P8's silent unit change multiplies one month's spend by a hundred. Those rows
    breach the source contract's declared maximum and are quarantined at ingestion, so
    an analytical detector must not be scored on them — on levels that single spike
    correlates all six media channels at 0.98 and hides everything else.
    """
    from insight_copilot.datagen.defects.schema import SilentUnitChange, _week_start

    starts = pd.Series([_week_start(str(label)) for label in index], index=index)
    return (starts >= SilentUnitChange.CHANGE_FROM) & (starts < SilentUnitChange.CHANGE_TO)


class FiscalVersusIsoCalendars(DefectInjector):
    """P18 — fiscal Apr-Mar alongside ISO weeks."""

    code: ClassVar[str] = "P18"
    title: ClassVar[str] = "Fiscal vs ISO calendars"
    complexity: ClassVar[str] = "Inconsistent calendars"
    exercises: ClassVar[str] = "Calendar spine"
    demo_moment: ClassVar[str] = "Contract"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames
        calendar = context.calendar
        spine = calendar.to_frame()
        # An ISO week that straddles the fiscal year boundary is the concrete form of
        # the mismatch: no rollup can be both fiscally and ISO-correct for that week.
        boundary = spine.loc[spine["fiscal_year"] != spine["fiscal_year"].shift(1)]
        straddling = 0
        for _, row in boundary.iterrows():
            week = row["iso_week"]
            same_week = spine.loc[spine["iso_week"] == week, "fiscal_year"].nunique()
            straddling += int(same_week > 1)
        return (
            self._found(
                f"{straddling} ISO weeks straddle a fiscal-year boundary",
                straddling_weeks=straddling,
            )
            if straddling > 0
            else self._missing("no ISO week straddles a fiscal boundary")
        )


class SparseHistory(DefectInjector):
    """P19 — "Aurora X" has 18 days of history against a 28-day contract minimum."""

    code: ClassVar[str] = "P19"
    title: ClassVar[str] = "Sparse history"
    complexity: ClassVar[str] = "Sparse history"
    exercises: ClassVar[str] = "Empirical-Bayes pooling, sparse policy"
    demo_moment: ClassVar[str] = "Scenario C"
    structural: ClassVar[bool] = True

    SIM_TODAY: ClassVar[dt.date] = dt.date(2026, 3, 29)

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames
        launches = [sku for sku in context.catalog.skus if sku.is_in_window_launch]
        recent = [sku for sku in launches if 0 < (self.SIM_TODAY - sku.launch_date).days < 28]
        comparables = [sku for sku in launches if (self.SIM_TODAY - sku.launch_date).days >= 56]
        return (
            self._found(
                f"{len(recent)} SKU below the 28-day minimum, with {len(comparables)} "
                f"comparable launches to pool over",
                sparse=len(recent),
                comparables=len(comparables),
            )
            if recent and len(comparables) >= 8
            else self._missing(
                f"{len(recent)} sparse SKUs, {len(comparables)} comparables",
                sparse=len(recent),
                comparables=len(comparables),
            )
        )


class IntermittentSeries(DefectInjector):
    """P20 — a slow SKU with many zero days. The Croston case."""

    code: ClassVar[str] = "P20"
    title: ClassVar[str] = "Intermittent series"
    complexity: ClassVar[str] = "Intermittent series"
    exercises: ClassVar[str] = "Croston path in the adaptation matrix"
    demo_moment: ClassVar[str] = "Adaptation table"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        oms = frames["oms_orders"]
        total_days = context.calendar.n_days
        selling_days = oms.groupby("product_sku", observed=True)["order_date"].nunique()
        zero_share = 1.0 - selling_days / total_days
        intermittent = int((zero_share > 0.40).sum())
        return (
            self._found(
                f"{intermittent} SKUs sell on fewer than 60% of days "
                f"(worst {zero_share.max():.1%} zero days)",
                intermittent_skus=intermittent,
                max_zero_share=float(zero_share.max()),
            )
            if intermittent >= 1
            else self._missing("no intermittent SKU")
        )


class LegitimateOutlier(DefectInjector):
    """P21 — a one-off institutional bulk order. A data event, never a trend."""

    code: ClassVar[str] = "P21"
    title: ClassVar[str] = "Legitimate outlier"
    complexity: ClassVar[str] = "Legitimate outlier"
    exercises: ClassVar[str] = "Materiality vs anomaly distinction"
    demo_moment: ClassVar[str] = "Specificity demo"

    ORDER_DATE: ClassVar[dt.date] = dt.date(2025, 12, 4)
    ORDER_VALUE_INR: ClassVar[float] = 1.2e7
    """Rs 1.2 crore in one day, from one institutional buyer, on modern trade."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        if "oms_orders" not in frames:
            return frames
        frame = frames["oms_orders"]
        candidates = frame.loc[
            (pd.to_datetime(frame["order_date"]).dt.date == self.ORDER_DATE)
            & (frame["channel"].astype(str) == "modern_trade")
        ]
        if candidates.empty:
            return frames
        row = candidates.iloc[0].copy()
        price = float(row["unit_price_net"]) or 1.0
        row["order_id"] = "ORD-INSTITUTIONAL-0001"
        row["units"] = int(self.ORDER_VALUE_INR / price)
        row["customer_segment"] = "new"
        row["returns_value"] = 0.0
        row["cancelled_units"] = 0
        del context
        result = frames.copy()
        result["oms_orders"] = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["oms_orders"]
        bulk = frame.loc[frame["order_id"].astype(str) == "ORD-INSTITUTIONAL-0001"]
        if bulk.empty:
            return self._missing("no institutional bulk order present")
        value = float((bulk["units"] * bulk["unit_price_net"]).sum())
        line_value = frame["units"] * frame["unit_price_net"]
        # Against the largest ORDINARY order line, not against a whole day. A day
        # aggregates a million lines; the point of this defect is that ONE line is
        # orders of magnitude beyond anything else in the book, which is exactly what
        # a robust detector must treat as a data event rather than a trend.
        ceiling = float(line_value.quantile(0.9999))
        return self._found(
            f"one order line worth Rs {value / 1e7:.2f} cr against a 99.99th-percentile "
            f"line of Rs {ceiling / 1e5:.1f} lakh ({value / max(ceiling, 1.0):.0f}x)",
            order_value_inr=value,
            multiple_of_p9999_line=value / max(ceiling, 1.0),
        )


class RegimeBreak(DefectInjector):
    """P22 — a permanent price-list revision shifting the level."""

    code: ClassVar[str] = "P22"
    title: ClassVar[str] = "Regime break"
    complexity: ClassVar[str] = "Regime break"
    exercises: ClassVar[str] = "Changepoint handling; calibration-window exclusion"
    demo_moment: ClassVar[str] = "Backtest"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames
        from insight_copilot.datagen.decisions.pricing import (
            REGIME_BREAK_DATE,
            REGIME_BREAK_SIZE,
        )

        offset = context.calendar.index_of(REGIME_BREAK_DATE)
        prices = context.simulator.price_plan.list_price.mean(axis=(0, 1))
        before = float(prices[offset - 30 : offset].mean())
        after = float(prices[offset : offset + 30].mean())
        step = after / before - 1.0
        return (
            self._found(f"list prices step {step:+.2%} at {REGIME_BREAK_DATE}", step=step)
            if abs(step - REGIME_BREAK_SIZE) < 0.02
            else self._missing(f"step is {step:+.2%}, expected {REGIME_BREAK_SIZE:+.2%}", step=step)
        )


class CollinearDrivers(DefectInjector):
    """P24 — paid social and display move together for two quarters."""

    code: ClassVar[str] = "P24"
    title: ClassVar[str] = "Collinear drivers"
    complexity: ClassVar[str] = "Collinear drivers"
    exercises: ClassVar[str] = "VIF gate -> grouped attribution"
    demo_moment: ClassVar[str] = "Scenario A diagnostics"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        config = context.config
        martech = frames["martech_weekly"]
        wide = martech.pivot_table(
            index="iso_week", columns="channel", values="spend_inr", aggfunc="sum", observed=True
        ).fillna(0.0)
        first, second = config.media.collinear_pair
        if first not in wide.columns or second not in wide.columns:
            return self._missing("the collinear pair is absent from the feed")

        from insight_copilot.datagen.defects.schema import _week_start

        wide = wide.loc[~_quarantined_weeks(wide.index).to_numpy()]
        starts = pd.Series(wide.index.map(_week_start), index=wide.index)
        window_start, window_end = config.media.collinear_window
        inside = (starts >= window_start) & (starts <= window_end)
        # LOG spend, not levels. P8's silent unit change multiplies one month's spend
        # by a hundred across every channel at once, and on levels that single spike
        # correlates all six channels at 0.98 and drowns the planted pair entirely.
        # The driver regression works in logs for the same reason.
        logged = pd.DataFrame(
            np.log(wide.to_numpy().clip(min=1.0)), index=wide.index, columns=wide.columns
        )
        within = float(logged.loc[inside, first].corr(logged.loc[inside, second]))
        outside = float(logged.loc[~inside, first].corr(logged.loc[~inside, second]))
        return (
            self._found(
                f"{first}/{second} correlate {within:.2f} inside the window "
                f"against {outside:.2f} outside",
                within=within,
                outside=outside,
            )
            if within > 0.6 and within > outside + 0.25
            else self._missing(
                f"correlation {within:.2f} inside, {outside:.2f} outside", within=within
            )
        )


class Endogeneity(DefectInjector):
    """P25 — media spend responds to last week's revenue.

    The one that makes naive OLS confidently wrong. Detected by the correlation
    between this week's spend and last week's revenue, which should not exist if
    budgets were exogenous.
    """

    code: ClassVar[str] = "P25"
    title: ClassVar[str] = "Endogeneity"
    complexity: ClassVar[str] = "Endogeneity"
    exercises: ClassVar[str] = "DAG specification, identification"
    demo_moment: ClassVar[str] = "Naive-vs-ours eval"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        martech = frames["martech_weekly"]
        spend = martech.groupby("iso_week", observed=True)["spend_inr"].sum().sort_index()
        oms = frames["oms_orders"].copy()
        oms["iso_week"] = pd.to_datetime(oms["order_date"]).dt.strftime("%G-W%V")
        revenue = (
            (oms["units"] * oms["unit_price_net"])
            .groupby(oms["iso_week"], observed=True)
            .sum()
            .sort_index()
        )
        joined = pd.concat([spend.rename("spend"), revenue.rename("revenue")], axis=1).dropna()
        joined = joined.loc[~_quarantined_weeks(joined.index).to_numpy()]
        joined = joined.loc[(joined > 0).all(axis=1)]
        correlation = float(joined["spend"].corr(joined["revenue"].shift(1)))
        return (
            self._found(
                f"spend correlates {correlation:.3f} with prior-week revenue",
                correlation=correlation,
            )
            if correlation > 0.10
            else self._missing(f"correlation only {correlation:.3f}", correlation=correlation)
        )


INJECTORS = [
    FiscalVersusIsoCalendars(),
    SparseHistory(),
    IntermittentSeries(),
    LegitimateOutlier(),
    RegimeBreak(),
    SimpsonsParadox(),
    CollinearDrivers(),
    Endogeneity(),
]
