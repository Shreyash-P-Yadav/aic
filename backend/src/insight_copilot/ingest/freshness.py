"""Freshness per source: green, amber, red — and the reason.

WHY freshness is measured against the *expected arrival*, not against wall-clock age:
a weekly feed is three days old the day after it lands and that is perfectly healthy.
Age alone would paint every weekly source permanently red and the tile would carry no
information. What matters is whether the drop that was *due* has turned up, and how
far past its SLA it is if not.

The schedule, from the source contract:

* **green**  — the latest due drop has arrived, or is not yet halfway to its SLA.
* **amber**  — it has not arrived and more than half the SLA has elapsed. This is the
  warning: the data is usable, and the engine should start hedging.
* **red**    — the SLA has been breached outright. This is a *hard gate*: the
  confidence layer forces ``INSUFFICIENT`` for any KPI that requires this source.
* **unknown** — nothing has ever arrived. Cold start, and treated as breached.

Pausing a feed therefore walks green to amber to red on a schedule the contract
declares, which is exactly what the demo's "break a feed" control shows.
"""

from __future__ import annotations

import datetime as dt

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.harness.scheduler import ArrivalScheduler
from insight_copilot.ingest.models import FreshnessState, FreshnessStatus
from insight_copilot.ingest.registry import BatchRegistry
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

AMBER_FRACTION = 0.5
"""Half the SLA elapsed with nothing delivered is when a human would start asking.
Below it the feed is merely unpunctual; above it, it is a problem worth surfacing."""


class FreshnessTracker:
    """Computes the freshness of every source at a simulated instant."""

    def __init__(
        self,
        registry: ContractRegistry,
        batches: BatchRegistry,
        scheduler: ArrivalScheduler,
    ) -> None:
        self._registry = registry
        self._batches = batches
        self._scheduler = scheduler

    def status(self, source_id: str, now: dt.datetime) -> FreshnessStatus:
        """Freshness for one source. Pure read; no side effects."""
        contract = self._registry.source(source_id)
        sla = contract.latency_sla_hours
        latest = self._batches.latest_batch(source_id)
        next_due = self._scheduler.next_arrival(source_id, now)
        due_at = self._last_due_before(source_id, now)

        if latest is None:
            return FreshnessStatus(
                source_id=source_id,
                state="unknown",
                last_batch_id=None,
                last_received_at=None,
                latest_period=None,
                age_hours=None,
                sla_hours=sla,
                next_due_at=next_due,
                detail=f"{source_id} has never delivered a batch",
            )

        received = _as_aware(latest["received_at"], now.tzinfo)
        age_hours = (now - received).total_seconds() / 3600.0
        overdue_hours = max((now - due_at).total_seconds() / 3600.0, 0.0)
        state = self._state(received >= due_at, overdue_hours, sla)
        return FreshnessStatus(
            source_id=source_id,
            state=state,
            last_batch_id=str(latest["batch_id"]),
            last_received_at=received,
            latest_period=self._batches.high_watermark(source_id),
            age_hours=age_hours,
            sla_hours=sla,
            next_due_at=next_due,
            detail=self._detail(source_id, state, received, due_at, overdue_hours, sla),
        )

    def all_statuses(self, now: dt.datetime) -> list[FreshnessStatus]:
        """Every source's freshness — the landing-zone monitor's whole payload."""
        return [self.status(source_id, now) for source_id in self._registry.source_ids]

    def breached_sources(self, now: dt.datetime) -> list[str]:
        """Sources whose SLA is breached. The confidence layer's hard gate reads this."""
        return [status.source_id for status in self.all_statuses(now) if status.breached]

    # ---------------------------------------------------------------- helpers --
    def _last_due_before(self, source_id: str, now: dt.datetime) -> dt.datetime:
        """The most recent moment this source was scheduled to deliver."""
        return self._scheduler.previous_arrival(source_id, now)

    @staticmethod
    def _state(arrived: bool, overdue_hours: float, sla_hours: float) -> FreshnessState:
        """Map arrival and lateness onto the tile colour."""
        if arrived or overdue_hours <= sla_hours * AMBER_FRACTION:
            return "green"
        if overdue_hours <= sla_hours:
            return "amber"
        return "red"

    @staticmethod
    def _detail(
        source_id: str,
        state: FreshnessState,
        received: dt.datetime,
        due_at: dt.datetime,
        overdue_hours: float,
        sla_hours: float,
    ) -> str:
        """A sentence a human can act on, not a status code."""
        if state == "green":
            return (
                f"{source_id} last delivered {received:%Y-%m-%d %H:%M}; the drop due "
                f"{due_at:%Y-%m-%d %H:%M} is accounted for"
            )
        return (
            f"{source_id} has not delivered the drop due {due_at:%Y-%m-%d %H:%M}; "
            f"{overdue_hours:.1f}h overdue against a {sla_hours:.0f}h SLA"
        )


def _as_aware(value: object, tzinfo: dt.tzinfo | None) -> dt.datetime:
    """Registry timestamps come back tz-aware from DuckDB, but in UTC.

    Converted to the caller's zone rather than merely compared in it, because these
    values are rendered in the freshness detail line and an operator reading "last
    delivered 18:30" about a batch that landed at midnight IST would reasonably
    conclude the tracker was broken.
    """
    moment = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        return moment.replace(tzinfo=tzinfo)
    return moment.astimezone(tzinfo) if tzinfo is not None else moment
