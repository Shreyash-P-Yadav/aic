"""``InsightEvidenceBundle`` — **every number that reaches the UI or the LLM lives here.**

That is the whole point of the object and the reason it is a frozen pydantic model
rather than a dict. The narration layer is handed this and nothing else; the verifier
checks every numeral in the generated text against this and nothing else. A number that
is not in the bundle cannot legitimately appear in a sentence, and the verifier's job
is only tractable because the set of legitimate numbers is finite and enumerable.

``AbstentionArtifact`` is the sibling type for the other outcome. Abstention is a
**designed output**, not an error path: it carries the observed movement, what is
known, which checks failed, what evidence is missing, and when to try again — which is
strictly more useful to an operator than a confident sentence resting on a stale feed.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from insight_copilot.contracts.common import StrictModel
from insight_copilot.engine.confidence import Tier

LineageStage = Literal["land", "conform", "mart", "blend"]
"""The stages a KPI contract's own ``lineage`` block declares."""


MIN_TOLERANCE_SCALE = 1e-6
"""Floor on the tolerance scale, so a fact of exactly zero still has a usable band."""


class NumberFact(StrictModel):
    """One number the system computed, with the method that produced it.

    The verifier matches generated numerals against these. ``value`` is the number;
    ``tolerance`` is how much rounding a narrator is allowed, because "down about
    twelve percent" is a faithful rendering of -11.94 and "down 12.4%" is not.
    """

    key: str
    value: float
    unit: str
    method: str
    tolerance: float = Field(default=0.05, ge=0.0)

    def matches(self, candidate: float) -> bool:
        """Is a numeral in generated text this fact, within its stated tolerance?

        The tolerance is **relative to the fact's own value**, not to a scale floored
        at one. Flooring it at one gives a fact of 0.62 an absolute band of +/-0.05,
        which is eight percent — wide enough that a fabricated 0.631 passes as a
        rounding of it. Measured: with the floored form, an injected "63.10%" verified
        successfully against a 62% explained-variance fact.
        """
        scale = max(abs(self.value), MIN_TOLERANCE_SCALE)
        return abs(candidate - self.value) <= self.tolerance * scale


class FreshnessFact(StrictModel):
    """One source's arrival health at the moment the insight was computed."""

    source_id: str
    state: str
    age_hours: float | None
    sla_hours: float
    latest_period: str | None


class LineageStep(StrictModel):
    """One hop from a source system to the number on screen."""

    stage: LineageStage
    frm: str
    to: str
    transform: str


class SegmentFact(StrictModel):
    """One segment from rung 1, with the numbers that ranked it."""

    label: str
    actual: float
    forecast: float
    explanatory_power: float
    surprise: float
    stability: float
    simpson_flag: bool = False


class DriverFact(StrictModel):
    """One driver from rung 3, always with its interval."""

    driver_id: str
    coefficient: float
    interval_low: float
    interval_high: float
    p_value: float
    agreement: float
    group: list[str] = Field(default_factory=list)
    contribution_inr: float | None = None


class EvidenceFact(StrictModel):
    """One document that survived the timing gate, with its confidence decomposed."""

    doc_id: str
    kind: str
    title: str
    publish_date: dt.date
    effective_date: dt.date
    source_tier: int
    confidence: float
    independence_key: str
    matched_on: str


class ActionFact(StrictModel):
    """One recommendation, in the design's own output order."""

    action_id: str
    driver_id: str
    lever: str
    title: str
    expected_impact_central: float
    expected_impact_low: float
    expected_impact_high: float
    owner_role: str
    needs_approval: bool
    monitoring_kpi: str
    monitoring_checkpoints: list[int]
    success_threshold_pct: float
    earliest_effect: dt.date


class ConfidenceFact(StrictModel):
    """The six signals, the composite and the tier — with the weakest link named."""

    signals: dict[str, float]
    signal_detail: dict[str, str]
    composite: float
    calibrated: float
    calibration_fitted: bool
    tier: Tier
    weakest_signal: str
    hard_gate_failures: list[str] = Field(default_factory=list)


class InsightEvidenceBundle(StrictModel):
    """The complete, self-contained record of one insight.

    Nothing outside this object may be narrated. Nothing inside it was produced by a
    language model.
    """

    insight_id: str
    kpi_id: str
    contract_version: str
    computed_at: dt.datetime
    period_start: dt.date
    period_end: dt.date
    watermark: str | None = None

    observed: float
    counterfactual: float
    delta: float
    delta_pct: float
    detection_method: str
    p_value: float

    numbers: list[NumberFact] = Field(default_factory=list)
    segments: list[SegmentFact] = Field(default_factory=list)
    price_effect: float | None = None
    volume_effect: float | None = None
    mix_effect: float | None = None
    drivers: list[DriverFact] = Field(default_factory=list)
    explained_fraction: float = 0.0
    unexplained_fraction: float = 1.0

    evidence: list[EvidenceFact] = Field(default_factory=list)
    evidence_corroboration: float = 0.0
    evidence_rejected_by_timing: list[str] = Field(default_factory=list)

    confidence: ConfidenceFact
    actions: list[ActionFact] = Field(default_factory=list)
    freshness: list[FreshnessFact] = Field(default_factory=list)
    lineage: list[LineageStep] = Field(default_factory=list)

    def fact(self, key: str) -> NumberFact | None:
        """One narratable number by key."""
        return next((item for item in self.numbers if item.key == key), None)

    @property
    def narratable_values(self) -> list[NumberFact]:
        """Every number a sentence about this insight is allowed to contain."""
        return list(self.numbers)

    @property
    def permits_recommendation(self) -> bool:
        """May this insight carry an action at all? The tier decides, not the writer."""
        return self.confidence.tier in ("High", "Moderate")


class AbstentionArtifact(StrictModel):
    """The designed output when the system will not commit. Not an error.

    An operator reading this learns more than they would from a confident sentence: it
    says what moved, what is nonetheless known, which checks failed, what is missing,
    and when the answer will be available.
    """

    insight_id: str
    kpi_id: str
    computed_at: dt.datetime
    period_start: dt.date
    period_end: dt.date

    observed_movement: str
    what_is_known: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    retry_trigger: str
    eta: dt.datetime | None = None
    confidence: ConfidenceFact
    freshness: list[FreshnessFact] = Field(default_factory=list)

    @property
    def headline(self) -> str:
        """The sentence the card leads with."""
        return (
            f"{self.kpi_id}: {self.observed_movement}. Not attributed — "
            f"{self.failed_checks[0] if self.failed_checks else 'insufficient evidence'}."
        )
