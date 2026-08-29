"""Typed results the ingestion pipeline hands to everything downstream.

Pydantic at every boundary, because these objects are read by the API, the evidence
drawer, the freshness tile and the ``c4`` data-trust confidence signal. A dict would
let a renamed field reach the UI as a blank tile rather than as a test failure.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from insight_copilot.contracts.common import StrictModel

BatchStatus = Literal["ingested", "skipped_duplicate", "quarantined", "rejected", "empty"]
FreshnessState = Literal["green", "amber", "red", "unknown"]
DQOutcome = Literal["pass", "warn", "quarantine", "reject"]
DriftKind = Literal["unexpected_column", "missing_column", "type_change"]


class QuarantineRecord(StrictModel):
    """Rows held back from silver, with the reason. **Nothing is ever dropped.**"""

    source_id: str
    batch_id: str
    rule: str
    reason: str
    row_count: int = Field(ge=0)
    row_hashes: list[str] = Field(default_factory=list)


class DQResult(StrictModel):
    """One expectation evaluated against one batch."""

    source_id: str
    batch_id: str
    expectation: str
    outcome: DQOutcome
    observed: float | None = None
    threshold: float | None = None
    rows_affected: int = 0
    detail: str = ""

    @property
    def passed(self) -> bool:
        """Did this expectation hold?"""
        return self.outcome == "pass"


class DriftAlert(StrictModel):
    """The delivered shape stopped matching the contract."""

    source_id: str
    batch_id: str
    kind: DriftKind
    columns: list[str]
    policy: str
    detail: str


class WatermarkState(StrictModel):
    """How far a source is complete, one row per period it has delivered."""

    source_id: str
    period: str
    batch_id: str
    updated_at: dt.datetime
    rewound: bool = False
    """True when a later batch re-opened a period that had already been closed."""


class FreshnessStatus(StrictModel):
    """Per-source arrival health — the tile, and the input to ``c4``."""

    source_id: str
    state: FreshnessState
    last_batch_id: str | None
    last_received_at: dt.datetime | None
    latest_period: str | None
    age_hours: float | None
    sla_hours: float
    next_due_at: dt.datetime | None
    detail: str

    @property
    def breached(self) -> bool:
        """Does this source breach its SLA? A hard confidence gate reads this."""
        return self.state in ("red", "unknown")


class DataLandedEvent(StrictModel):
    """Emitted per successful load. **Wakes only the KPIs that depend on the source.**

    This is why the analytics layer is event-driven rather than cron-driven: a MarTech
    drop wakes ``blended_roas`` and ``marketing_spend`` and does not re-scan fill rate.
    Work happens when data changes, which is both correct engineering and the whole
    cost story.
    """

    source_id: str
    batch_id: str
    periods: list[str]
    affected_days: list[dt.date]
    watermark_rewound: bool
    wakes_kpis: list[str]
    received_at: dt.datetime


class IngestResult(StrictModel):
    """Everything one batch did to the warehouse."""

    source_id: str
    batch_id: str
    status: BatchStatus
    periods: list[str]
    rows_delivered: int = 0
    rows_landed: int = 0
    rows_quarantined: int = 0
    rows_deduplicated: int = 0
    dq_results: list[DQResult] = Field(default_factory=list)
    drift: list[DriftAlert] = Field(default_factory=list)
    quarantine: list[QuarantineRecord] = Field(default_factory=list)
    event: DataLandedEvent | None = None
    detail: str = ""

    @property
    def accepted(self) -> bool:
        """Did any row reach bronze under this batch?"""
        return self.status in ("ingested", "quarantined")


class ReconciliationResult(StrictModel):
    """One contract-declared cross-source agreement, measured."""

    left: str
    right: str
    measure: str
    window: str
    periods_checked: int
    median_abs_delta_pct: float
    max_abs_delta_pct: float
    tolerance_pct: float
    breached: bool
    on_breach: str
    detail: str
