"""P1-P6 — how data arrives: cadence, grain, restatement, lateness, gaps, duplicates.

These are the pathologies that live in the *arrival process* rather than in the rows,
which is why the prototype watches files land instead of reading a finished warehouse.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd

from insight_copilot.datagen.defects.base import DefectEvidence, DefectInjector
from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames


class DifferentCadences(DefectInjector):
    """P1 — daily, weekly, T+2 and static feeds side by side."""

    code: ClassVar[str] = "P1"
    title: ClassVar[str] = "Different refresh cadences"
    complexity: ClassVar[str] = "Different refresh cadences"
    exercises: ClassVar[str] = "Freshness tracker, arrival scheduler"
    demo_moment: ClassVar[str] = "Landing-zone monitor"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames, context
        from insight_copilot.contracts.registry import ContractRegistry

        registry = ContractRegistry.from_directory(_contracts_dir())
        cadences = {registry.source(sid).covers.period for sid in registry.source_ids}
        wanted = {"previous_day", "previous_iso_week", "t_minus_2", "continuous", "static"}
        found = cadences & wanted
        return (
            self._found(f"cadences present: {sorted(found)}", distinct=len(found))
            if len(found) >= 4
            else self._missing(f"only {sorted(found)}", distinct=len(found))
        )


def _contracts_dir() -> Path:
    """Where the shipped contract YAMLs live."""
    import insight_copilot.contracts as contracts_package

    return Path(contracts_package.__file__).resolve().parent


class DifferentGrains(DefectInjector):
    """P2 — SKU-day against campaign-week against SKU-master."""

    code: ClassVar[str] = "P2"
    title: ClassVar[str] = "Different grains"
    complexity: ClassVar[str] = "Different grains"
    exercises: ClassVar[str] = "Contract compiler, grain alignment"
    demo_moment: ClassVar[str] = "Evidence drawer lineage"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        grains = {
            "oms_orders": frozenset(["order_date", "product_sku", "region", "channel"]),
            "martech_weekly": frozenset(["iso_week", "campaign_id", "channel"]),
            "wms_fulfilment": frozenset(["ship_date", "warehouse", "product_sku"]),
            "pim_products": frozenset(["product_sku"]),
        }
        actual = {
            source: grain
            for source, grain in grains.items()
            if source in frames and grain <= set(frames[source].columns)
        }
        distinct = len({frozenset(value) for value in actual.values()})
        return (
            self._found(f"{distinct} distinct grains across {len(actual)} sources", grains=distinct)
            if distinct >= 4
            else self._missing(f"only {distinct} distinct grains", grains=distinct)
        )


class Restatement(DefectInjector):
    """P3 — MarTech revises the last fortnight on every drop.

    Injected as *duplicate rows for recent weeks with revised figures*. The landing
    layer (P5) turns those into superseding batches; here the point is that the
    revised values exist and differ from the originals.
    """

    code: ClassVar[str] = "P3"
    title: ClassVar[str] = "Restatement"
    complexity: ClassVar[str] = "Restatement"
    exercises: ClassVar[str] = "Watermark rewind, supersede-by-batch"
    demo_moment: ClassVar[str] = "Scenario B"

    RESTATEMENT_DRIFT: ClassVar[float] = 0.06
    """Typical revision size. Attribution settles upward as view-throughs land."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        if "martech_weekly" not in frames:
            return frames
        frame = frames["martech_weekly"]
        weeks = sorted(frame["iso_week"].unique())
        # The most recent two weeks of every drop are revised; taking the last two
        # weeks of history stands in for "every drop" at generation time.
        recent = set(weeks[-2:])
        revised = frame.loc[frame["iso_week"].isin(recent)].copy()
        seeds = context.simulator.seeds
        drift = 1.0 + self.RESTATEMENT_DRIFT * seeds("restatement").normal(0.0, 1.0, len(revised))
        revised["attributed_revenue_inr"] = (
            revised["attributed_revenue_inr"] * np.abs(drift)
        ).round(2)
        revised["spend_inr"] = (revised["spend_inr"] * 1.0).round(2)
        result = frames.copy()
        result["martech_weekly"] = pd.concat([frame, revised], ignore_index=True)
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["martech_weekly"]
        keys = ["iso_week", "campaign_id", "channel"]
        duplicated = frame.duplicated(subset=keys, keep=False)
        if not duplicated.any():
            return self._missing("no restated rows present")
        grouped = (
            frame.loc[duplicated].groupby(keys, observed=True)["attributed_revenue_inr"].nunique()
        )
        changed = int((grouped > 1).sum())
        return self._found(
            f"{int(duplicated.sum())} restated rows, {changed} with revised values",
            restated_rows=float(duplicated.sum()),
            revised=float(changed),
        )


class LateArrival(DefectInjector):
    """P4 — the WMS extract lands T+2, sometimes T+3."""

    code: ClassVar[str] = "P4"
    title: ClassVar[str] = "Late arrival"
    complexity: ClassVar[str] = "Late arrival"
    exercises: ClassVar[str] = "Lag-aware labelling ('as of T-2')"
    demo_moment: ClassVar[str] = "Scenario A card"

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["wms_fulfilment"]
        lag = (
            pd.to_datetime(frame["extracted_at_ts"]) - pd.to_datetime(frame["ship_date"])
        ).dt.total_seconds() / 86400.0
        median = float(lag.median())
        return (
            self._found(f"median extract lag {median:.2f} days", median_lag_days=median)
            if median >= 2.0
            else self._missing(f"extract lag only {median:.2f} days", median_lag_days=median)
        )


class MissingPeriod(DefectInjector):
    """P5 — one MarTech week never arrives. The hard freshness gate, and Scenario B."""

    code: ClassVar[str] = "P5"
    title: ClassVar[str] = "Missing period"
    complexity: ClassVar[str] = "Missing period"
    exercises: ClassVar[str] = "Freshness hard gate"
    demo_moment: ClassVar[str] = "Scenario B abstention"

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        missed = _scenario_b_missing_weeks(context)
        if not missed or "martech_weekly" not in frames:
            return frames
        frame = frames["martech_weekly"]
        result = frames.copy()
        result["martech_weekly"] = frame.loc[~frame["iso_week"].isin(missed)].reset_index(drop=True)
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        missed = _scenario_b_missing_weeks(context)
        present = set(frames["martech_weekly"]["iso_week"].unique())
        absent = sorted(missed - present)
        return (
            self._found(f"weeks absent from the feed: {absent}", missing_weeks=len(absent))
            if absent
            else self._missing("no missing MarTech week")
        )


def _scenario_b_missing_weeks(context: ProjectionContext) -> set[str]:
    """ISO weeks the MarTech drop never delivered, from the scenario ledger."""
    calendar = context.calendar
    missed: set[str] = set()
    for event in context.ledger:
        if event.demo_role != "scenario_B_primary":
            continue
        inside = (calendar.dates.date >= event.window.start) & (
            calendar.dates.date <= event.window.end
        )
        # The drop due inside the window covers the PREVIOUS ISO week.
        for label in set(calendar.iso_week[inside]):
            year, week = label.split("-W")
            previous = dt.date.fromisocalendar(int(year), int(week), 1) - dt.timedelta(days=7)
            iso = previous.isocalendar()
            missed.add(f"{iso.year}-W{iso.week:02d}")
    return missed


class DuplicateDelivery(DefectInjector):
    """P6a — the same batch delivered twice. Caught by the batch registry."""

    code: ClassVar[str] = "P6a"
    title: ClassVar[str] = "Duplicate delivery"
    complexity: ClassVar[str] = "Duplicate delivery"
    exercises: ClassVar[str] = "Idempotency by batch registry"
    demo_moment: ClassVar[str] = "Ingestion log"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames
        # A duplicate *delivery* is an arrival-time event, not a row-level one: the
        # same batch_id lands twice. It is realised by the landing zone in P5 and
        # asserted there; here the catalog records that the contract declares the
        # idempotency key that makes it detectable at all.
        from insight_copilot.contracts.registry import ContractRegistry

        del context
        registry = ContractRegistry.from_directory(_contracts_dir())
        keyed = [
            source_id
            for source_id in registry.source_ids
            if "batch_id" in registry.source(source_id).idempotency
        ]
        return (
            self._found(f"{len(keyed)} sources declare batch_id idempotency", sources=len(keyed))
            if len(keyed) >= 9
            else self._missing(f"only {len(keyed)} sources are idempotent by batch")
        )


class SilentDuplication(DefectInjector):
    """P6b — the same rows under a new batch id. Caught by row-hash dedup."""

    code: ClassVar[str] = "P6b"
    title: ClassVar[str] = "Silent duplication"
    complexity: ClassVar[str] = "Silent duplication"
    exercises: ClassVar[str] = "Dedup by row_hash"
    demo_moment: ClassVar[str] = "Ingestion log"

    DUPLICATE_DAY: ClassVar[dt.date] = dt.date(2025, 6, 17)
    """The OMS export ran twice on this day. A known issue on the contract."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        del context
        if "oms_orders" not in frames:
            return frames
        frame = frames["oms_orders"]
        repeated = frame.loc[pd.to_datetime(frame["order_date"]).dt.date == self.DUPLICATE_DAY]
        if repeated.empty:
            return frames
        result = frames.copy()
        result["oms_orders"] = pd.concat([frame, repeated], ignore_index=True)
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["oms_orders"]
        keys = ["order_date", "order_id", "product_sku", "region", "channel"]
        duplicated = int(frame.duplicated(subset=keys).sum())
        return (
            self._found(f"{duplicated} exactly-duplicated rows", duplicate_rows=duplicated)
            if duplicated > 0
            else self._missing("no silently duplicated rows")
        )


INJECTORS = [
    DifferentCadences(),
    DifferentGrains(),
    Restatement(),
    LateArrival(),
    MissingPeriod(),
    DuplicateDelivery(),
    SilentDuplication(),
]
