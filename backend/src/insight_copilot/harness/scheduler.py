"""``ArrivalScheduler`` — turns eleven source contracts into a stream of arrivals.

Every field it reads is contract-declared: the cron, the timezone, the jitter
envelope, the probability that a drop simply does not happen, and the restatement
window. Nothing about *when* data shows up is hard-coded here, which is the whole
point of having an arrival contract.

WHY jitter and failure are drawn content-addressed rather than sequentially: the
same replay must produce the same late nights and the same missed drops on every
run, or "the MarTech feed went dark on the 16th" would be a different date each
time the demo is rehearsed. The key is ``(source_id, scheduled_at)``, so adding a
twelfth source perturbs nothing about the other eleven.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.datagen.world.seeds import RNGSource
from insight_copilot.harness.cron import CronSchedule
from insight_copilot.harness.periods import periods_for
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

TRANSPORT_LATENCY_SECONDS = 4
"""Wire time between a producer cutting a file and the watcher seeing it. Small, but
non-zero: ``received_at`` must never equal ``generated_at_sim`` or the two fields in
the manifest would be indistinguishable and the freshness maths untestable."""


@dataclass(frozen=True)
class PlannedArrival:
    """One scheduled drop, resolved to the minute it actually lands — or does not."""

    source_id: str
    scheduled_at: dt.datetime
    arrives_at: dt.datetime
    received_at: dt.datetime
    periods: tuple[str, ...]
    is_restatement: bool
    delivered: bool
    covers_from: dt.datetime | None
    """Lower bound of the row slice for a continuous feed; ``None`` for periodic ones."""

    @property
    def delay(self) -> dt.timedelta:
        """How late this drop was against its cron time."""
        return self.arrives_at - self.scheduled_at


class ArrivalScheduler:
    """Plans arrivals for every source over a window of simulated time."""

    def __init__(self, registry: ContractRegistry, seeds: RNGSource) -> None:
        self._registry = registry
        self._seeds = seeds
        self._crons: dict[str, CronSchedule] = {
            source_id: CronSchedule.parse(registry.source(source_id).arrival.cron)
            for source_id in registry.source_ids
        }

    # ------------------------------------------------------------------ plan --
    def plan_source(
        self, source_id: str, start: dt.datetime, end: dt.datetime
    ) -> list[PlannedArrival]:
        """Every drop this source schedules in ``(start, end]``, delivered or not."""
        contract = self._registry.source(source_id)
        zone = ZoneInfo(contract.arrival.tz)
        cron = self._crons[source_id]
        firings = cron.between(start.astimezone(zone), end.astimezone(zone))
        return [self._resolve(contract, cron, firing) for firing in firings]

    def plan_all(self, start: dt.datetime, end: dt.datetime) -> list[PlannedArrival]:
        """Every source's drops in ``(start, end]``, ordered by the moment they land.

        Ordering by arrival rather than by schedule is deliberate: a jittered WMS drop
        can overtake the next day's OMS drop, and the pipeline must cope with
        out-of-order periods because that is what actually happens.
        """
        planned = [
            arrival
            for source_id in self._registry.source_ids
            for arrival in self.plan_source(source_id, start, end)
        ]
        planned.sort(key=lambda arrival: (arrival.received_at, arrival.source_id))
        logger.info(
            "scheduler.planned",
            arrivals=len(planned),
            delivered=sum(1 for arrival in planned if arrival.delivered),
            frm=start.isoformat(),
            to=end.isoformat(),
        )
        return planned

    def next_arrival(self, source_id: str, after: dt.datetime) -> dt.datetime:
        """When this source is next *due*. Freshness compares against this, not now."""
        contract = self._registry.source(source_id)
        zone = ZoneInfo(contract.arrival.tz)
        return self._crons[source_id].next_after(after.astimezone(zone))

    def previous_arrival(self, source_id: str, before: dt.datetime) -> dt.datetime:
        """The most recent moment this source was *due*. The freshness baseline."""
        contract = self._registry.source(source_id)
        zone = ZoneInfo(contract.arrival.tz)
        return self._crons[source_id].previous_before(before.astimezone(zone))

    # -------------------------------------------------------------- resolve --
    def _resolve(
        self, contract: SourceContract, cron: CronSchedule, scheduled_at: dt.datetime
    ) -> PlannedArrival:
        """Apply jitter and the failure roll to one cron firing."""
        arrival = contract.arrival
        rng = self._seeds("arrival", contract.source_id, scheduled_at.isoformat())
        # One generator, two draws in a fixed order: jitter first, then the failure
        # roll. Fixing the order is what keeps a contract's jitter change from also
        # changing which drops go missing.
        jitter = float(rng.random()) * float(arrival.jitter_minutes)
        delivered = float(rng.random()) >= arrival.failure_probability

        arrives_at = scheduled_at + dt.timedelta(minutes=jitter)
        received_at = arrives_at + dt.timedelta(seconds=TRANSPORT_LATENCY_SECONDS)
        periods = periods_for(contract, scheduled_at)
        covers_from = (
            cron.previous_before(scheduled_at) if contract.covers.period == "continuous" else None
        )
        return PlannedArrival(
            source_id=contract.source_id,
            scheduled_at=scheduled_at,
            arrives_at=arrives_at,
            received_at=received_at,
            periods=periods,
            is_restatement=contract.restatement.expected and len(periods) > 1,
            delivered=delivered,
            covers_from=covers_from,
        )


def manual_arrival(
    source_id: str,
    periods: tuple[str, ...],
    moment: dt.datetime,
    *,
    is_restatement: bool = False,
) -> PlannedArrival:
    """An arrival a person caused rather than a cron: a re-drop, a late backfill.

    The file is cut a moment before it appears and is *on disk* at ``moment``, so the
    very next poll of a clock sitting at ``moment`` sees it. Adding the usual transport
    latency instead would put every operator-triggered drop one tick into the future,
    and a demo button whose effect only shows up on the next tick is a broken button.
    """
    return PlannedArrival(
        source_id=source_id,
        scheduled_at=moment - dt.timedelta(seconds=TRANSPORT_LATENCY_SECONDS),
        arrives_at=moment,
        received_at=moment,
        periods=periods,
        is_restatement=is_restatement,
        delivered=True,
        covers_from=None,
    )
