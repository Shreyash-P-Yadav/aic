"""Application state: the objects every route shares, wired once and injected.

The state is deliberately *lazy* about the expensive things. Constructing the app must
not generate a 36-month world or open a warehouse, because the API has to start in
milliseconds for a health check and for the test suite. The warehouse-backed routes ask
for what they need and get a typed error when it is not there — which is also what a
cold-started deployment looks like before the first backfill.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from insight_copilot.api.schemas import KpiSeriesResponse
from insight_copilot.config import Settings, get_settings
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.engine.bundle import AbstentionArtifact, InsightEvidenceBundle
from insight_copilot.errors import ServiceUnavailable
from insight_copilot.llm.feedback import ClassifiedFeedback, FeedbackClassifier
from insight_copilot.llm.narrate import PersonaNarrator
from insight_copilot.llm.provider import build_provider
from insight_copilot.llm.router import ModelRouter
from insight_copilot.logging import get_logger
from insight_copilot.security.audit import AuditLog, InMemoryAuditLog
from insight_copilot.security.identity import ROLES, Identity, RoleName, SessionContext
from insight_copilot.telemetry.meter import TelemetryLedger

logger = get_logger(__name__)

SPARK_POINTS = 60
"""Days of history behind each card's sparkline. Two months is enough to read a
seasonal shape and short enough that the movement being reported is still visible."""

DEFAULT_ROLE: RoleName = "analyst"
"""The role a session starts in. An analyst sees method detail, which is the most
useful default for a demo and the least surprising for a developer."""


class WarehouseUnavailable(ServiceUnavailable):
    """A warehouse-backed route was called before any data was loaded.

    A subclass rather than a bare error so the API returns 503 — a cold start is a
    documented state of this system, not an internal failure.
    """


@dataclass
class InsightRecord:
    """One produced output, plus the narratives rendered from it."""

    insight_id: str
    kpi_id: str
    created_at: dt.datetime
    bundle: InsightEvidenceBundle | None = None
    abstention: AbstentionArtifact | None = None
    narratives: dict[str, str] = field(default_factory=dict)
    feedback: list[ClassifiedFeedback] = field(default_factory=list)
    series: KpiSeriesResponse | None = None
    """The KPI's history and counterfactual, attached by whatever produced the insight.

    Held on the record rather than inside the evidence bundle on purpose: the bundle is
    the audited contract of what was computed and narrated, and a 939-point chart series
    is a presentation concern that would bloat every serialisation of it.
    """

    @property
    def status(self) -> str:
        """``published`` or ``abstained`` — the two things this system produces."""
        return "abstained" if self.abstention is not None else "published"

    @property
    def tier(self) -> str:
        """The confidence tier, whichever output type carries it."""
        source = self.bundle or self.abstention
        return source.confidence.tier if source else "Insufficient"

    @property
    def delta_pct(self) -> float:
        """The movement, for the list view."""
        return self.bundle.delta_pct if self.bundle else 0.0

    @property
    def impact(self) -> float | None:
        """The movement in the KPI's own unit. ``None`` on an abstention: there is no
        impact to quote for a movement the system declined to attribute."""
        return self.bundle.delta if self.bundle else None

    @property
    def unit(self) -> str:
        """The unit ``impact`` is in, read from the bundle's own ``delta`` fact."""
        if self.bundle is None:
            return "INR"
        fact = self.bundle.fact("delta")
        return fact.unit if fact else "INR"

    @property
    def top_segment(self) -> str | None:
        """The leading segment's label, or ``None`` when nothing was named."""
        if self.bundle is None or not self.bundle.segments:
            return None
        return self.bundle.segments[0].label

    def spark(self, points: int = SPARK_POINTS) -> list[float]:
        """The tail of the actual series, for the card's sparkline.

        Deliberately the raw values, not an index: the sparkline carries shape only —
        it has no axis and no labels — so rescaling it would imply a precision the mark
        is not making.
        """
        if self.series is None:
            return []
        return list(self.series.actual[-points:])


class AppState:
    """Everything the routes share. One instance per application."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.registry = ContractRegistry.from_directory(self.settings.contracts_dir)
        self.audit: AuditLog = InMemoryAuditLog()
        self.telemetry = TelemetryLedger()
        self.router = ModelRouter(build_provider(self.settings), self.settings)
        self.narrator = PersonaNarrator(self.router)
        self.classifier = FeedbackClassifier(self.router)
        self.insights: dict[str, InsightRecord] = {}
        self.session = SessionContext(
            identity=Identity(
                user_id="demo@example.com",
                display_name=ROLES[DEFAULT_ROLE].display_name,
                role=ROLES[DEFAULT_ROLE],
            ),
            intent="api",
        )
        self._warehouse: object | None = None
        self._world: object | None = None
        self._harness: object | None = None
        self._controls: object | None = None

    # ------------------------------------------------------------------ roles --
    def set_role(self, role: RoleName) -> SessionContext:
        """Switch role. This changes the *data*, not just the label.

        Row filters and column masks live in the contract compiler, below the LLM and
        below this API, so a role change is a data fact rather than a UI toggle.
        """
        self.session = SessionContext(
            identity=Identity(
                user_id=self.session.identity.user_id,
                display_name=ROLES[role].display_name,
                role=ROLES[role],
            ),
            intent="api",
        )
        logger.info("api.role_changed", role=role, run_id=self.session.run_id)
        return self.session

    # -------------------------------------------------------------- warehouse --
    def attach_warehouse(
        self,
        warehouse: object,
        harness: object | None = None,
        controls: object | None = None,
        world: object | None = None,
    ) -> None:
        """Give the state a loaded warehouse. Called by the demo and the CLI."""
        self._warehouse = warehouse
        self._harness = harness
        self._controls = controls
        self._world = world

    @property
    def world(self) -> object:
        """The generated world, needed to re-run a scan after a demo control.

        Held here rather than passed through every call because a control arrives as an
        HTTP request with no access to whatever the CLI happened to build at startup.
        """
        if self._world is None:
            raise ServiceUnavailable(
                "no world is attached",
                detail="start the API with `insight-copilot demo` so controls can re-scan",
            )
        return self._world

    @property
    def warehouse(self) -> object:
        """The warehouse, or a typed error a route turns into a 503."""
        if self._warehouse is None:
            raise WarehouseUnavailable(
                "no warehouse is attached",
                detail="run `make backfill` (or `make demo`) before calling this route",
            )
        return self._warehouse

    @property
    def harness(self) -> object:
        """The replay harness, for the demo controls."""
        if self._harness is None:
            raise WarehouseUnavailable(
                "no replay harness is attached",
                detail="the demo controls need a running harness; start it with `make demo`",
            )
        return self._harness

    @property
    def harness_controls(self) -> object:
        """The demo controls, for the two admin routes."""
        if self._controls is None:
            raise WarehouseUnavailable(
                "the demo controls are not attached",
                detail="start the harness with `make demo` before using the admin panel",
            )
        return self._controls

    @property
    def has_warehouse(self) -> bool:
        """Is warehouse-backed data available? Routes branch on this, never on a try."""
        return self._warehouse is not None

    # --------------------------------------------------------------- insights --
    def store(self, record: InsightRecord) -> InsightRecord:
        """Record one produced output."""
        self.insights[record.insight_id] = record
        return record

    def list_insights(
        self, *, status: str | None = None, kpi_id: str | None = None
    ) -> list[InsightRecord]:
        """Insights newest first, optionally filtered."""
        records = sorted(self.insights.values(), key=lambda item: item.created_at, reverse=True)
        if status:
            records = [item for item in records if item.status == status]
        if kpi_id:
            records = [item for item in records if item.kpi_id == kpi_id]
        return records

    def artifacts_dir(self) -> Path:
        """Where eval reports and screenshots live."""
        return self.settings.artifacts_dir
