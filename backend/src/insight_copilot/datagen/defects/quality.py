"""P12-P17 — data quality: nulls, unknown members, hierarchy change, coverage, matching.

The family that makes a dimension untrustworthy rather than a number wrong. Each one
degrades what the engine can *say*, not what it can compute — which is why they feed
the confidence signals rather than the DQ hard gates.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

import pandas as pd

from insight_copilot.datagen.defects.base import DefectEvidence, DefectInjector
from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames


class NullSpike(DefectInjector):
    """P12 — the region mapping breaks for three days."""

    code: ClassVar[str] = "P12"
    title: ClassVar[str] = "Null spike"
    complexity: ClassVar[str] = "Null spike"
    exercises: ClassVar[str] = "DQ null-fraction gate"
    demo_moment: ClassVar[str] = "DQ dashboard"

    WINDOW: ClassVar[tuple[dt.date, dt.date]] = (dt.date(2025, 9, 8), dt.date(2025, 9, 10))
    AFFECTED_SHARE: ClassVar[float] = 0.34

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        if "oms_orders" not in frames:
            return frames
        frame = frames["oms_orders"].copy()
        dates = pd.to_datetime(frame["order_date"]).dt.date
        inside = (dates >= self.WINDOW[0]) & (dates <= self.WINDOW[1])
        picked = inside & (
            context.simulator.seeds("null_spike").random(len(frame)) < self.AFFECTED_SHARE
        )
        frame["region"] = frame["region"].astype(str)
        frame.loc[picked, "region"] = "UNKNOWN"
        result = frames.copy()
        result["oms_orders"] = frame
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["oms_orders"]
        dates = pd.to_datetime(frame["order_date"]).dt.date
        inside = (dates >= self.WINDOW[0]) & (dates <= self.WINDOW[1])
        share = float((frame.loc[inside, "region"].astype(str) == "UNKNOWN").mean())
        return (
            self._found(f"{share:.1%} of rows lose their region in the window", share=share)
            if share > 0.15
            else self._missing(f"only {share:.1%} unknown-region rows", share=share)
        )


class UnknownMembers(DefectInjector):
    """P13 — new SKUs transact before the PIM knows about them.

    Structural: the PIM projector already stamps a launched SKU's master row nine days
    after its launch date, so the OMS reports sales for a SKU the master cannot
    classify. That is the mechanism behind Scenario C's launch appearing without a
    category for over a week.
    """

    code: ClassVar[str] = "P13"
    title: ClassVar[str] = "Unknown members"
    complexity: ClassVar[str] = "Unknown members"
    exercises: ClassVar[str] = "UNKNOWN bucket + flag"
    demo_moment: ClassVar[str] = "Scenario C"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        pim = frames["pim_products"].set_index("product_sku")["valid_from"]
        oms = frames["oms_orders"]
        launched = {sku.sku_id for sku in context.catalog.skus if sku.is_in_window_launch}
        orphaned = 0
        for sku_id in launched:
            rows = oms.loc[oms["product_sku"].astype(str) == sku_id]
            if rows.empty:
                continue
            known_from = pd.Timestamp(pim.loc[sku_id])
            orphaned += int((pd.to_datetime(rows["order_date"]) < known_from).sum())
        return (
            self._found(
                f"{orphaned} order lines predate their SKU's product-master row",
                orphaned_rows=orphaned,
            )
            if orphaned > 0
            else self._missing("every order line has a known product master")
        )


class HierarchyChange(DefectInjector):
    """P14 — two regions merge mid-history, so the dimension is slowly-changing."""

    code: ClassVar[str] = "P14"
    title: ClassVar[str] = "Hierarchy change"
    complexity: ClassVar[str] = "Hierarchy change"
    exercises: ClassVar[str] = "Slowly-changing dimension handling"
    demo_moment: ClassVar[str] = "Analyst view"

    MERGE_DATE: ClassVar[dt.date] = dt.date(2024, 10, 1)
    MERGED: ClassVar[tuple[str, str]] = ("Central", "North")
    """A territory restructure: Central was folded into North's reporting line. Rows
    before the merge still say Central, rows after say North — so a naive
    year-on-year comparison for either region is wrong in both directions."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        del context
        if "oms_orders" not in frames:
            return frames
        frame = frames["oms_orders"].copy()
        frame["region"] = frame["region"].astype(str)
        after = pd.to_datetime(frame["order_date"]).dt.date >= self.MERGE_DATE
        merged = after & (frame["region"] == self.MERGED[0])
        frame.loc[merged, "region"] = self.MERGED[1]
        result = frames.copy()
        result["oms_orders"] = frame
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["oms_orders"]
        dates = pd.to_datetime(frame["order_date"]).dt.date
        region = frame["region"].astype(str)
        before = float((region.loc[dates < self.MERGE_DATE] == self.MERGED[0]).mean())
        after = float((region.loc[dates >= self.MERGE_DATE] == self.MERGED[0]).mean())
        return (
            self._found(
                f"{self.MERGED[0]!r} is {before:.1%} of rows before the merge and "
                f"{after:.1%} after",
                share_before=before,
                share_after=after,
            )
            if before > 0.02 and after < 0.005
            else self._missing(
                "no hierarchy change visible", share_before=before, share_after=after
            )
        )


class PartialCoverage(DefectInjector):
    """P15 — the competitor panel covers only ~60% of our SKUs."""

    code: ClassVar[str] = "P15"
    title: ClassVar[str] = "Partial coverage"
    complexity: ClassVar[str] = "Partial coverage"
    exercises: ClassVar[str] = "Coverage-aware confidence"
    demo_moment: ClassVar[str] = "Confidence breakdown"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        matched = set(frames["competitor_prices"]["matched_sku"].astype(str).unique())
        total = len(context.catalog.skus)
        coverage = len(matched) / total
        return (
            self._found(f"{coverage:.1%} SKU coverage", coverage=coverage)
            if 0.40 <= coverage <= 0.80
            else self._missing(
                f"coverage {coverage:.1%} outside the designed band", coverage=coverage
            )
        )


class FuzzyEntityMatch(DefectInjector):
    """P16 — competitor SKU matching is probabilistic, at ~85% mean confidence."""

    code: ClassVar[str] = "P16"
    title: ClassVar[str] = "Fuzzy entity match"
    complexity: ClassVar[str] = "Fuzzy entity match"
    exercises: ClassVar[str] = "EntityLinkConf in evidence"
    demo_moment: ClassVar[str] = "Evidence drawer"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        confidence = frames["competitor_prices"]["match_confidence"]
        mean = float(confidence.mean())
        weak = float((confidence < 0.75).mean())
        return (
            self._found(
                f"mean match confidence {mean:.3f}, {weak:.1%} below 0.75",
                mean_confidence=mean,
                weak_share=weak,
            )
            if 0.75 <= mean <= 0.93 and weak > 0.02
            else self._missing(
                f"match confidence {mean:.3f} is not a real distribution", mean_confidence=mean
            )
        )


class ShortExternalHistory(DefectInjector):
    """P17 — competitor data starts 14 months in; MarTech holds only 12."""

    code: ClassVar[str] = "P17"
    title: ClassVar[str] = "Short external history"
    complexity: ClassVar[str] = "Short external history"
    exercises: ClassVar[str] = "Window selection, model eligibility"
    demo_moment: ClassVar[str] = "Analyst view"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        horizon = context.config.horizon
        internal_days = (horizon.end - horizon.start).days
        competitor = frames["competitor_prices"]
        earliest = min(
            dt.date.fromisocalendar(int(w.split("-W")[0]), int(w.split("-W")[1]), 1)
            for w in competitor["iso_week"].unique()
        )
        external_days = (horizon.end - earliest).days
        ratio = external_days / internal_days
        return (
            self._found(
                f"competitor history is {external_days} days against {internal_days} internal "
                f"({ratio:.2f}x)",
                external_days=external_days,
                internal_days=internal_days,
            )
            if ratio < 0.6
            else self._missing(f"external history is {ratio:.2f} of internal", ratio=ratio)
        )


INJECTORS = [
    NullSpike(),
    UnknownMembers(),
    HierarchyChange(),
    PartialCoverage(),
    FuzzyEntityMatch(),
    ShortExternalHistory(),
]
