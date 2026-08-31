"""The harness loop: clock, scheduler, landing zone, watcher, ingestion.

This is the object the CLI, the demo controls and the P5 gate all drive. It owns the
one honest statement about how the prototype gets its data: *nothing reads a finished
table*. Every row that reaches gold arrived as a file, was seen by a watcher, and went
through the same bronze-to-gold path a production deployment would use.

Three entry points, matching the design's operating modes:

* :meth:`backfill` — bulk historical load from the beginning of the horizon to a
  go-live date, exactly as a real deployment would begin. Also the cold-start demo.
* :meth:`advance_to` — replay to a simulated instant, landing and ingesting every
  batch due in between, in the order they actually arrive.
* :meth:`step` — one arrival at a time under manual control.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.datagen.projection.base import SourceFrames
from insight_copilot.datagen.world.seeds import RNGSource
from insight_copilot.harness.clock import SimClock
from insight_copilot.harness.landing import LandedBatch, LandingZone, SourceWatcher
from insight_copilot.harness.periods import STATIC_PERIOD, day_label, week_label
from insight_copilot.harness.quirks import BatchQuirk, default_quirks
from insight_copilot.harness.scheduler import (
    TRANSPORT_LATENCY_SECONDS,
    ArrivalScheduler,
    PlannedArrival,
)
from insight_copilot.harness.slicer import PeriodSlicer
from insight_copilot.ingest.expectations import validate_registry
from insight_copilot.ingest.freshness import FreshnessTracker
from insight_copilot.ingest.models import FreshnessStatus, IngestResult
from insight_copilot.ingest.runner import IngestionRunner
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

DRAIN_CHUNK = dt.timedelta(days=1)
"""Batches are landed and ingested one simulated day at a time. Small enough that a
late feed still overtakes an early one inside the window, large enough that a
half-hourly ticket feed does not trigger forty-eight silver rebuilds a day."""


@dataclass
class ReplaySummary:
    """What one replay window did."""

    frm: dt.datetime
    to: dt.datetime
    planned: int = 0
    landed: int = 0
    missed: int = 0
    results: list[IngestResult] = field(default_factory=list)

    @property
    def rows_landed(self) -> int:
        """Rows that reached bronze."""
        return sum(result.rows_landed for result in self.results)

    @property
    def rows_quarantined(self) -> int:
        """Rows held back from silver, with a reason recorded for each."""
        return sum(result.rows_quarantined for result in self.results)

    @property
    def duplicates_skipped(self) -> int:
        """Batches recognised by the registry and ignored."""
        return sum(1 for result in self.results if result.status == "skipped_duplicate")


class ReplayHarness:
    """Drives simulated time and the whole intake path."""

    def __init__(
        self,
        *,
        clock: SimClock,
        registry: ContractRegistry,
        frames: SourceFrames,
        warehouse: Warehouse,
        landing: LandingZone,
        seeds: RNGSource,
        horizon: tuple[dt.date, dt.date],
        quirks: list[BatchQuirk] | None = None,
    ) -> None:
        validate_registry(registry)
        self._horizon = horizon
        self._clock = clock
        self._registry = registry
        self._landing = landing
        self._scheduler = ArrivalScheduler(registry, seeds)
        self._slicer = PeriodSlicer(frames)
        self._quirks = quirks if quirks is not None else default_quirks(seeds)
        self._watcher = SourceWatcher(landing)
        self._runner = IngestionRunner(warehouse, registry)
        self._freshness = FreshnessTracker(registry, self._runner.batch_registry, self._scheduler)
        self._paused: set[str] = set()

    # ----------------------------------------------------------------- state --
    @property
    def clock(self) -> SimClock:
        """The simulated clock. The demo controls move it."""
        return self._clock

    @property
    def runner(self) -> IngestionRunner:
        """The ingestion runner, for callers that need the batch registry."""
        return self._runner

    @property
    def landing(self) -> LandingZone:
        """The landing zone, for callers that need to inspect the files."""
        return self._landing

    @property
    def contracts(self) -> ContractRegistry:
        """The contract registry this harness was built against."""
        return self._registry

    @property
    def slicer(self) -> PeriodSlicer:
        """Cuts batches out of the generated world. The demo controls reuse it."""
        return self._slicer

    @property
    def watcher(self) -> SourceWatcher:
        """The landing-zone watcher, for callers that need to force a rescan."""
        return self._watcher

    @property
    def paused_sources(self) -> set[str]:
        """Feeds currently held. The "break a feed" control adds to this."""
        return set(self._paused)

    def pause(self, source_id: str) -> None:
        """Stop a feed delivering. Freshness walks green to amber to red from here."""
        self._registry.source(source_id)
        self._paused.add(source_id)
        logger.info("harness.feed_paused", source_id=source_id, at=self._clock.now.isoformat())

    def resume(self, source_id: str) -> None:
        """Let a paused feed deliver again. Its backlog lands on the next advance."""
        self._paused.discard(source_id)
        logger.info("harness.feed_resumed", source_id=source_id, at=self._clock.now.isoformat())

    def freshness(self) -> list[FreshnessStatus]:
        """Every source's freshness at the current simulated instant."""
        return self._freshness.all_statuses(self._clock.now)

    # ---------------------------------------------------------------- replay --
    def advance_to(self, moment: dt.datetime) -> ReplaySummary:
        """Land and ingest everything due between now and ``moment``."""
        start = self._clock.now
        target = self._clock.localise(moment)
        summary = ReplaySummary(frm=start, to=target)
        if target <= start:
            return summary
        cursor = start
        while cursor < target:
            chunk_end = min(cursor + DRAIN_CHUNK, target)
            self._land_window(cursor, chunk_end, summary)
            self._clock.travel_to(chunk_end)
            summary.results.extend(self._drain())
            cursor = chunk_end
        logger.info(
            "harness.replayed",
            frm=start.isoformat(),
            to=target.isoformat(),
            planned=summary.planned,
            landed=summary.landed,
            missed=summary.missed,
            rows=summary.rows_landed,
        )
        return summary

    def advance_days(self, days: int) -> ReplaySummary:
        """Replay a whole number of simulated days."""
        return self.advance_to(self._clock.now + dt.timedelta(days=days))

    def backfill(self, start: dt.date, go_live: dt.date) -> ReplaySummary:
        """Bulk historical load, then leave the clock at the go-live moment.

        A backfill is emphatically **not** a replay at speed. A real deployment loads
        history in one pass — one extract per source covering everything up to the day
        it goes live — and only then starts watching for drops. Modelling it that way
        is both far cheaper than replaying forty thousand historical arrivals and more
        honest: it is why the cold-start case (a KPI that has thirty-six months of
        history the moment the system comes up, and a launch SKU that has eighteen
        days) is a fact about the load rather than an assertion about it.
        """
        zone = self._clock.timezone
        cutover = dt.datetime.combine(go_live, dt.time.min, zone)
        self._clock.travel_to(cutover)
        summary = ReplaySummary(frm=dt.datetime.combine(start, dt.time.min, zone), to=cutover)
        for source_id in self._registry.source_ids:
            contract = self._registry.source(source_id)
            arrival = historical_arrival(contract, start, cutover)
            summary.planned += 1
            summary.landed += 1
            self._write(arrival)
        self._watcher.rescan()
        summary.results.extend(self._drain())
        # The spine covers the whole modelled horizon, not just the loaded part: it
        # is a dimension table, and a replay that ran past its last row would join
        # every new day to nothing and silently lose its holiday flags.
        self._runner.build_calendar(self._horizon[0], self._horizon[1])
        logger.info(
            "harness.backfilled",
            frm=start.isoformat(),
            to=go_live.isoformat(),
            sources=summary.landed,
            rows=summary.rows_landed,
        )
        return summary

    def step(self) -> ReplaySummary:
        """Advance one clock step and process whatever that brought."""
        return self.advance_to(self._clock.now + self._clock.step_size)

    # ------------------------------------------------------------------ land --
    def land(self, arrival: PlannedArrival) -> LandedBatch:
        """Cut and land one arrival now. The demo controls' single entry point."""
        return self._write(arrival)

    def land_frame(
        self, arrival: PlannedArrival, frame: pd.DataFrame, *, producer_note: str | None = None
    ) -> LandedBatch:
        """Land rows a caller has already prepared — a hand-built restatement, say."""
        contract = self._registry.source(arrival.source_id)
        return self._landing.land(contract, frame, arrival, producer_note=producer_note)

    def drain(self) -> list[IngestResult]:
        """Ingest everything the watcher can see right now."""
        return self._drain()

    def _land_window(
        self, start: dt.datetime, end: dt.datetime, summary: ReplaySummary
    ) -> list[LandedBatch]:
        """Write every batch due in ``(start, end]`` into the landing zone."""
        landed: list[LandedBatch] = []
        for arrival in self._scheduler.plan_all(start, end):
            summary.planned += 1
            if arrival.source_id in self._paused:
                summary.missed += 1
                continue
            if not arrival.delivered:
                summary.missed += 1
                logger.info(
                    "harness.drop_missed",
                    source_id=arrival.source_id,
                    scheduled=arrival.scheduled_at.isoformat(),
                )
                continue
            landed.append(self._write(arrival))
            summary.landed += 1
        return landed

    def _write(self, arrival: PlannedArrival) -> LandedBatch:
        """Cut the batch from the generated world, apply quirks, and land it."""
        contract = self._registry.source(arrival.source_id)
        frame = self._slicer.slice(contract, arrival)
        note = None
        for quirk in self._quirks:
            if quirk.applies_to(contract, arrival):
                frame = quirk.mutate(frame, contract, arrival)
                note = type(quirk).__name__
        return self._landing.land(contract, frame, arrival, producer_note=note)

    def _drain(self) -> list[IngestResult]:
        """Ingest everything the watcher can see at the current instant."""
        batches = self._watcher.poll(self._clock.now)
        if not batches:
            return []
        return self._runner.ingest_many(batches, sim_time=self._clock.now)


def historical_arrival(
    contract: SourceContract, start: dt.date, cutover: dt.datetime
) -> PlannedArrival:
    """One synthetic arrival covering every period from ``start`` up to go-live.

    The historical extract is a single delivery, so it carries a single batch id and a
    single manifest listing every period it covers. Everything downstream — bronze
    provenance, period-scoped silver rebuilds, watermarks — then works on the bulk load
    with no special case, because the bulk load is just a very wide batch.
    """
    # The extract is cut a moment before go-live and is *on disk* at go-live, so the
    # first poll of the watching clock sees it. Cutting it at go-live and adding the
    # usual transport latency would put it one tick into the future and the system
    # would come up empty.
    return PlannedArrival(
        source_id=contract.source_id,
        scheduled_at=cutover - dt.timedelta(seconds=TRANSPORT_LATENCY_SECONDS),
        arrives_at=cutover,
        received_at=cutover,
        periods=historical_periods(contract, start, cutover.date()),
        is_restatement=False,
        delivered=True,
        covers_from=dt.datetime.combine(start, dt.time.min, cutover.tzinfo) - dt.timedelta(days=1),
    )


def historical_periods(
    contract: SourceContract, start: dt.date, go_live: dt.date
) -> tuple[str, ...]:
    """Every period label the historical extract closes, newest first."""
    if contract.covers.period == "static":
        return (STATIC_PERIOD,)
    if contract.covers.period == "previous_iso_week":
        weeks: list[str] = []
        cursor = start
        while cursor < go_live:
            label = week_label(cursor)
            if label not in weeks:
                weeks.append(label)
            cursor += dt.timedelta(days=1)
        return tuple(reversed(weeks))
    days = [
        day_label(start + dt.timedelta(days=offset)) for offset in range((go_live - start).days)
    ]
    return tuple(reversed(days))
