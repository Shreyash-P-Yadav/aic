"""P7-P11 — the shape of the data changing underneath you.

The scariest family. A renamed column fails loudly; a **silently changed unit** does
not. It multiplies every downstream number by a hundred and every chart still renders.
Only a range expectation on the source contract catches it, which is why the contract
carries `min` and `max` on every numeric column.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

import pandas as pd

from insight_copilot.datagen.defects.base import DefectEvidence, DefectInjector
from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames


class SchemaDrift(DefectInjector):
    """P7 — `spend_inr` becomes `spend_amount` at a known date.

    Applied as an added alias column rather than a rename, because a projected frame
    must still satisfy its source contract. The landing layer writes the alias into
    the batch for the affected period, and the drift policy quarantines it.
    """

    code: ClassVar[str] = "P7"
    title: ClassVar[str] = "Schema drift"
    complexity: ClassVar[str] = "Schema drift"
    exercises: ClassVar[str] = "Drift detection -> quarantine"
    demo_moment: ClassVar[str] = "Admin panel"

    DRIFT_FROM: ClassVar[dt.date] = dt.date(2025, 11, 3)
    RENAMED_TO: ClassVar[str] = "spend_amount"

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["martech_weekly"]
        affected = _weeks_from(frame, self.DRIFT_FROM)
        return (
            self._found(
                f"{len(affected)} weeks from {self.DRIFT_FROM} deliver "
                f"{self.RENAMED_TO!r} in place of 'spend_inr'",
                affected_weeks=len(affected),
            )
            if affected
            else self._missing("no weeks fall after the declared drift date")
        )


class SilentUnitChange(DefectInjector):
    """P8 — paise become rupees in the MarTech feed. **The scariest one.**

    A 100x jump in every spend figure with no schema change, no error, and no
    complaint from any join. Every ROAS number becomes wrong by two orders of
    magnitude and every chart still looks like a chart. The ONLY thing that catches
    it is the `max` range expectation on `spend_inr` in the source contract — which is
    exactly why every numeric column in every source contract carries one.
    """

    code: ClassVar[str] = "P8"
    title: ClassVar[str] = "Silent unit change"
    complexity: ClassVar[str] = "Silent unit change"
    exercises: ClassVar[str] = "Range expectations catch a 100x jump"
    demo_moment: ClassVar[str] = "Admin panel — the scariest one"

    CHANGE_FROM: ClassVar[dt.date] = dt.date(2025, 2, 3)
    CHANGE_TO: ClassVar[dt.date] = dt.date(2025, 3, 3)
    FACTOR: ClassVar[float] = 100.0
    """Paise to rupees. The feed reported paise for a month and nobody said so."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        del context
        if "martech_weekly" not in frames:
            return frames
        frame = frames["martech_weekly"].copy()
        affected = _week_mask(frame, self.CHANGE_FROM, self.CHANGE_TO)
        frame.loc[affected, "spend_inr"] = (frame.loc[affected, "spend_inr"] * self.FACTOR).round(2)
        result = frames.copy()
        result["martech_weekly"] = frame
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["martech_weekly"]
        affected = _week_mask(frame, self.CHANGE_FROM, self.CHANGE_TO)
        if not affected.any():
            return self._missing("no rows fall inside the unit-change window")
        inside = float(frame.loc[affected, "spend_inr"].median())
        outside = float(frame.loc[~affected, "spend_inr"].median())
        ratio = inside / max(outside, 1e-9)
        # The contract's declared ceiling is what an ingestion DQ gate would use.
        over_ceiling = int((frame.loc[affected, "spend_inr"] > 50_000_000).sum())
        return (
            self._found(
                f"median spend inside the window is {ratio:.0f}x the rest; "
                f"{over_ceiling} rows exceed the contract's declared maximum",
                ratio=ratio,
                rows_over_contract_max=over_ceiling,
            )
            if ratio > 50.0
            else self._missing(f"only a {ratio:.1f}x jump", ratio=ratio)
        )


class TimezoneMismatch(DefectInjector):
    """P9 — one source stamps UTC while everything else is IST."""

    code: ClassVar[str] = "P9"
    title: ClassVar[str] = "Timezone mismatch"
    complexity: ClassVar[str] = "Timezone mismatch"
    exercises: ClassVar[str] = "Timezone normalisation at silver"
    demo_moment: ClassVar[str] = "Boundary-day reconciliation"

    OFFSET_HOURS: ClassVar[float] = -5.5
    """IST is UTC+05:30, so a UTC-stamped feed reads five and a half hours early —
    which moves every order placed before 05:30 IST onto the previous day."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        del context
        if "support_tickets" not in frames:
            return frames
        frame = frames["support_tickets"].copy()
        shift = pd.Timedelta(hours=self.OFFSET_HOURS)
        frame["opened_at_ts"] = pd.to_datetime(frame["opened_at_ts"]) + shift
        frame["resolved_at_ts"] = pd.to_datetime(frame["resolved_at_ts"]) + shift
        result = frames.copy()
        result["support_tickets"] = frame
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        # The business key disagrees with the timestamp. A ticket id encodes the IST
        # date the ticket was raised; a UTC-stamped `opened_at_ts` for anything raised
        # before 05:30 IST falls on the PREVIOUS calendar day. That mismatch is what a
        # silver-layer conformance rule actually catches, and it needs no
        # distributional assumption about when people raise tickets — which matters,
        # because comparing circular mean hours against a near-uniform reference feed
        # is unstable enough to be useless.
        tickets = frames["support_tickets"]
        stamped = pd.to_datetime(tickets["opened_at_ts"]).dt.strftime("%Y%m%d")
        keyed = tickets["ticket_id"].astype(str).str.slice(4, 12)
        mismatched = float((stamped != keyed).mean())
        return (
            self._found(
                f"{mismatched:.1%} of tickets carry a timestamp on a different calendar "
                f"day from the one their id encodes, consistent with a UTC stamp against IST",
                mismatch_share=mismatched,
            )
            if mismatched > 0.02
            else self._missing(
                f"only {mismatched:.1%} of tickets disagree with their own key",
                mismatch_share=mismatched,
            )
        )


class DefinitionalChange(DefectInjector):
    """P10 — `net_revenue` stops including shipping. Handled by contract versioning.

    Structural: the change is a governance fact recorded in the KPI contract's
    version history, not a transformation of rows. What makes it detectable is that
    the contract carries a version at all, and that every audit row pins it.
    """

    code: ClassVar[str] = "P10"
    title: ClassVar[str] = "Definitional change"
    complexity: ClassVar[str] = "Definitional change"
    exercises: ClassVar[str] = "Contract versioning"
    demo_moment: ClassVar[str] = "Governance story"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames, context
        from insight_copilot.contracts.registry import ContractRegistry
        from insight_copilot.datagen.defects.arrival import _contracts_dir

        registry = ContractRegistry.from_directory(_contracts_dir())
        contract = registry.kpi("net_revenue")
        major, minor, patch = (int(part) for part in contract.contract_version.split("."))
        excludes_shipping = "shipping" in contract.kpi.description.lower()
        return (
            self._found(
                f"net_revenue is at contract v{contract.contract_version} and its "
                f"description states the shipping treatment explicitly",
                version_minor=minor + patch * 0.01 + major * 0,
            )
            if (major, minor) >= (1, 1) and excludes_shipping
            else self._missing("net_revenue does not record a definitional history")
        )


class CurrencyMismatch(DefectInjector):
    """P11 — a small export unit reports USD. Converted at a policy rate-date."""

    code: ClassVar[str] = "P11"
    title: ClassVar[str] = "Currency"
    complexity: ClassVar[str] = "Currency"
    exercises: ClassVar[str] = "FX conversion with a rate-date policy"
    demo_moment: ClassVar[str] = "Silver transform"

    EXPORT_REGION: ClassVar[str] = "East"
    EXPORT_CHANNEL: ClassVar[str] = "marketplace"
    USD_RATE: ClassVar[float] = 83.4
    """The export unit's books are in USD. Rows arrive ~83x smaller with no marker
    other than the region and channel combination — so only the range expectation
    and the conformance rule catch it."""

    SHARE: ClassVar[float] = 0.03
    """A small unit: about 3% of that channel's rows in that region."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        if "oms_orders" not in frames:
            return frames
        frame = frames["oms_orders"].copy()
        selector = (frame["region"] == self.EXPORT_REGION) & (
            frame["channel"] == self.EXPORT_CHANNEL
        )
        seeds = context.simulator.seeds
        picked = selector & (seeds("currency_export").random(len(frame)) < self.SHARE)
        for column in ("unit_price_net", "list_price", "returns_value"):
            frame.loc[picked, column] = (frame.loc[picked, column] / self.USD_RATE).round(4)
        result = frames.copy()
        result["oms_orders"] = frame
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        frame = frames["oms_orders"]
        implausible = frame["unit_price_net"] < 20.0
        count = int(implausible.sum())
        return (
            self._found(
                f"{count} order lines priced below Rs 20, consistent with a USD-denominated unit",
                rows=count,
            )
            if count > 0
            else self._missing("no currency-mismatched rows")
        )


def _week_mask(frame: pd.DataFrame, start: dt.date, end: dt.date) -> pd.Series:
    """Boolean mask over ISO-week labels falling inside a date range."""
    starts = frame["iso_week"].map(_week_start)
    return (starts >= start) & (starts < end)


def _weeks_from(frame: pd.DataFrame, start: dt.date) -> list[str]:
    """ISO weeks at or after a date."""
    return sorted({week for week in frame["iso_week"].unique() if _week_start(week) >= start})


def _week_start(label: str) -> dt.date:
    """Monday of an ISO week label like ``2026-W11``."""
    year, week = label.split("-W")
    return dt.date.fromisocalendar(int(year), int(week), 1)


INJECTORS = [
    SchemaDrift(),
    SilentUnitChange(),
    TimezoneMismatch(),
    DefinitionalChange(),
    CurrencyMismatch(),
]
