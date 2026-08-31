"""The eval report as data. The markdown is a rendering of this, never the source.

Every measurement carries its own target and its own ``n``. A metric printed without
the count behind it invites the reader to trust a number computed on four events, and
a metric printed without its target invites the writer to decide afterwards what would
have counted as passing.
"""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from insight_copilot.contracts.common import StrictModel


class Measurement(StrictModel):
    """One measured number against one stated target."""

    name: str
    value: float
    target: float | None = None
    direction: str = "max"
    """``max`` when the target is a ceiling the value must stay under, ``min`` when it
    is a floor the value must clear."""
    n: int = 0
    unit: str = ""
    detail: str = ""

    @property
    def measured(self) -> bool:
        """Was this actually computed? An unmeasured metric is never a pass."""
        return self.n > 0 and self.value == self.value  # NaN is never equal to itself

    @property
    def passed(self) -> bool | None:
        """``None`` when there is no target — informational metrics have none."""
        if self.target is None:
            return None
        if not self.measured:
            return False
        return self.value <= self.target if self.direction == "max" else self.value >= self.target

    @property
    def verdict(self) -> str:
        """PASS, FAIL or the honest dash for a metric with no target."""
        outcome = self.passed
        return "—" if outcome is None else ("PASS" if outcome else "FAIL")


class ReliabilityRow(StrictModel):
    """One reliability-curve bin, with its count."""

    lower: float
    upper: float
    n: int
    mean_score: float
    hit_rate: float


class TierRow(StrictModel):
    """One tier's observed hit rate in the backtest, with its count."""

    tier: str
    n: int
    hit_rate: float
    mean_score: float
    boundary: float


class EvalSection(StrictModel):
    """A named group of measurements, with room for a table under it."""

    name: str
    detail: str = ""
    measurements: list[Measurement] = Field(default_factory=list)

    @property
    def failures(self) -> list[Measurement]:
        """Everything in this section that missed its target."""
        return [item for item in self.measurements if item.passed is False]


class EvalReport(StrictModel):
    """Everything ``make verify-p11`` measured, in one serialisable object."""

    generated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    cut_date: dt.date | None = None
    corpus_events: int = 0
    fit_events: int = 0
    holdout_events: int = 0
    excluded_events: int = 0
    sections: list[EvalSection] = Field(default_factory=list)
    reliability: list[ReliabilityRow] = Field(default_factory=list)
    tiers: list[TierRow] = Field(default_factory=list)
    tier_basis: str = ""
    ranker_status: str = ""
    notes: list[str] = Field(default_factory=list)

    @property
    def measurements(self) -> list[Measurement]:
        """Every measurement across every section."""
        return [item for section in self.sections for item in section.measurements]

    @property
    def failures(self) -> list[Measurement]:
        """Every metric that missed its target. The gate reads this."""
        return [item for item in self.measurements if item.passed is False]

    @property
    def passed(self) -> bool:
        """Did every metric with a target meet it?"""
        return not self.failures
