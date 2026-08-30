"""Shared API response models.

WHY pydantic at the boundary: the build standard forbids dicts crossing module
boundaries. The generated OpenAPI schema is then also the frontend's contract, so a
renamed field breaks the TypeScript build rather than a demo.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: Literal["ok"] = "ok"
    version: str
    llm_provider: str
    environment: str


class ProblemDetail(BaseModel):
    """RFC-7807-shaped error body.

    WHY: errors must never return a stack trace. The ``type`` field is the exception
    class name so a client can branch on it, and ``reason`` carries policy text
    verbatim for entitlement denials.
    """

    type: str
    title: str
    status: int
    detail: str | None = None
    reason: str | None = None
    instance: str | None = Field(default=None, description="run_id or request path")


class RoleSummary(BaseModel):
    """One selectable role and what it may see."""

    name: str
    display_name: str
    description: str
    bindings: dict[str, str] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """The active session. Changing the role changes the data, not just the label."""

    user_id: str
    role: str
    display_name: str
    run_id: str


class RoleRequest(BaseModel):
    """Switch the active role."""

    role: str


class InsightSummary(BaseModel):
    """One row of the insight list."""

    insight_id: str
    kpi_id: str
    status: Literal["published", "abstained"]
    tier: str
    delta_pct: float
    created_at: str
    headline: str
    impact: float | None = None
    """The KPI's own movement in its own unit. Spec-mandated on the card and previously
    missing, which left a reader with a percentage and no sense of what it was worth."""
    unit: str = "INR"
    """The unit ``impact`` is measured in. Sent because the card was rendering a count
    of units as "Rs -21,082" — the same class of error the number verifier caught in the
    narration, and one a UI has no way to avoid without being told the unit."""
    top_segment: str | None = None
    """The leading segment, so the card answers "where" without a click."""
    spark: list[float] = Field(default_factory=list)
    """A short recent history for the card's sparkline. Sent with the list rather than
    fetched per card, because one request that answers the screen beats N that each
    answer a tile."""


class KpiSeriesResponse(BaseModel):
    """The KPI's own history, with the counterfactual it was judged against.

    The product's whole claim is "this moved, against what we expected" — and until
    now the UI showed the two scalars and never the two lines. One axis, two series in
    the same unit, so no dual-axis rule is in play; the detection window is returned
    separately so the chart can shade the period that was held out of the fit rather
    than leaving a reader to infer it.
    """

    kpi_id: str
    unit: str
    dates: list[str]
    actual: list[float]
    counterfactual: list[float]
    window_start: str | None = None
    window_end: str | None = None

    @property
    def points(self) -> int:
        """How many days the series covers."""
        return len(self.dates)


class NarrativeResponse(BaseModel):
    """A rendered narrative and the verification behind it."""

    persona: str
    tier: str
    text: str
    source: str
    attempts: int
    numbers_checked: int
    numbers_unsupported: int
    faithfulness: float
    cached: bool


class FeedbackRequest(BaseModel):
    """A reader's reaction. The only labelled signal this system ever gets."""

    text: str


class FeedbackResponse(BaseModel):
    """The classified reaction."""

    insight_id: str
    label: str
    reason: str
    method: str


class AskRequest(BaseModel):
    """A conversational question."""

    question: str
    kpi_id: str | None = None


class AskResponse(BaseModel):
    """Either an answer with its bundle, or a clarifying question."""

    kind: Literal["answer", "clarification"]
    question: str | None = None
    insight_id: str | None = None
    narrative: str | None = None
    detail: str


class SourceSummary(BaseModel):
    """One feed, from its contract and its arrival history."""

    source_id: str
    system: str
    owner: str
    cadence: str
    format: str
    quality_tier: str
    latency_sla_hours: float
    known_issues: list[str] = Field(default_factory=list)


class BatchSummary(BaseModel):
    """One landed batch, from the registry."""

    batch_id: str
    periods: list[str]
    received_at: str
    row_count: int
    rows_quarantined: int
    status: str
    is_restatement: bool


class FreshnessResponse(BaseModel):
    """One source's arrival health."""

    source_id: str
    state: str
    age_hours: float | None
    sla_hours: float
    latest_period: str | None
    detail: str


class DQResponse(BaseModel):
    """One data-quality finding."""

    source_id: str
    expectation: str
    outcome: str
    observed: float | None
    threshold: float | None
    rows_affected: int
    detail: str


class TelemetryResponse(BaseModel):
    """What the model layer has cost."""

    insights_metered: int
    mean_usd_per_insight: float
    mean_inr_per_insight: float
    total_usd: float
    model_calls: int
    cache_hits: int
    downgrades: int


class CalibrationResponse(BaseModel):
    """Whether the confidence map is fitted, and on what."""

    fitted: bool
    n_points: int
    detail: str


class EvalMeasurement(BaseModel):
    """One measured number against its stated target."""

    section: str = ""
    """Which area of the system this measures. Carried through so twenty-five rows can
    be grouped on screen instead of read as one undifferentiated list."""
    name: str
    value: float
    target: float | None = None
    direction: str = "max"
    unit: str = ""
    n: int = 0
    detail: str = ""
    verdict: str = "—"


class ReliabilityBin(BaseModel):
    """One bin of the reliability curve, always carrying its own count."""

    lower: float
    upper: float
    n: int
    mean_score: float
    hit_rate: float


class TierRow(BaseModel):
    """One tier's observed hit rate in the backtest, with its count."""

    tier: str
    n: int
    hit_rate: float
    mean_score: float
    boundary: float


class EvalReportResponse(BaseModel):
    """The backtest, as the Trust screen renders it.

    Served from the artifact the eval suite wrote rather than recomputed on request: a
    backtest is a seven-minute job over 416 events, and a screen that recomputed it per
    page view would be lying about what it costs to know this.
    """

    available: bool
    generated_at: str | None = None
    corpus_events: int = 0
    fit_events: int = 0
    holdout_events: int = 0
    cut_date: str | None = None
    tier_basis: str = ""
    measurements: list[EvalMeasurement] = Field(default_factory=list)
    reliability: list[ReliabilityBin] = Field(default_factory=list)
    tiers: list[TierRow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    detail: str = ""


class AuditEntry(BaseModel):
    """One audited action."""

    run_id: str
    event: str
    role: str
    contract_id: str | None
    outcome: str
    reason: str | None
    rows_returned: int | None


class DemoControlRequest(BaseModel):
    """A demo control invocation."""

    target: str = Field(description="Event id for inject-event, source id for break-feed.")


class DemoControlResponse(BaseModel):
    """What the control did."""

    control: str
    detail: str
    sim_time: str
