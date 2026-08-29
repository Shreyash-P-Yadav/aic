"""``DemoControls`` — the four buttons that turn a scripted demo into something a judge
can poke.

The risk this module manages is stated in the design and is worth repeating: an
interactive control that misbehaves on stage is worse than no control. Each of these
has one scripted happy path, a tested reset, and — importantly — an honest scope.

1. **Inject event.** Runs one of the *planted* ledger events now: the clock jumps to
   just before its window and the feeds carrying it land. It does not synthesise a new
   event, because a genuinely new event would require re-running the simulation and
   recomputing its counterfactual, and a number the ground-truth ledger cannot vouch
   for has no business on this stage. What the judge chooses is *when it breaks*, not
   whether the break is real.
2. **Break a feed.** Pauses a source. Freshness walks green to amber to red on the
   contract's own SLA schedule, ``c4`` decays, and the engine moves from publishing to
   hedging to abstaining. Interactive abstention, not narrated abstention.
3. **Send a restatement.** Re-drops a period, revised. The figure changes, the insight
   supersedes itself, and both versions stay queryable in bronze.
4. **Time-travel.** Moves the clock to any date and rebuilds state to match.

Plus a **reset** that returns the warehouse, the landing zone and the clock to the
state a rehearsal starts from.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from insight_copilot.datagen.events.ledger import EventLedger
from insight_copilot.datagen.world.seeds import RNGSource
from insight_copilot.errors import IngestionError
from insight_copilot.harness.quirks import RestatementQuirk
from insight_copilot.harness.replay import ReplayHarness, ReplaySummary
from insight_copilot.harness.scheduler import manual_arrival
from insight_copilot.ingest.models import FreshnessStatus, IngestResult
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

INJECT_LEAD_DAYS = 2
"""The clock lands two days before an injected event's window so the audience sees the
last healthy batch before the break, not just the break."""

INJECT_FOLLOW_DAYS = 9
"""Enough days after the window opens for the T+2 warehouse feed to have reported it
and for the weekly marketing drop to have landed at least once."""


@dataclass(frozen=True)
class ControlOutcome:
    """What a control did, in terms an operator can read back on the admin panel."""

    control: str
    detail: str
    sim_time: dt.datetime
    results: tuple[IngestResult, ...] = ()
    freshness: tuple[FreshnessStatus, ...] = ()


class DemoControls:
    """The interactive surface over the replay harness."""

    def __init__(
        self,
        harness: ReplayHarness,
        warehouse: Warehouse,
        ledger: EventLedger,
        seeds: RNGSource,
        *,
        horizon_start: dt.date,
    ) -> None:
        self._harness = harness
        self._warehouse = warehouse
        self._ledger = ledger
        self._restater = RestatementQuirk(seeds)
        self._horizon_start = horizon_start

    # -------------------------------------------------------------- 1. inject --
    def injectable_events(self) -> list[str]:
        """Ledger events with a demo role — the ones the button may run."""
        return [event.event_id for event in self._ledger if event.demo_role]

    def inject_event(self, event_id: str) -> ControlOutcome:
        """Run a planted event now: jump to just before it and replay through it."""
        event = self._event(event_id)
        lead = dt.datetime.combine(
            event.window.start - dt.timedelta(days=INJECT_LEAD_DAYS),
            dt.time.min,
            self._harness.clock.timezone,
        )
        self.time_travel(lead.date())
        summary = self._harness.advance_days(INJECT_FOLLOW_DAYS + INJECT_LEAD_DAYS)
        logger.info("controls.injected", event_id=event_id, landed=summary.landed)
        return ControlOutcome(
            control="inject_event",
            detail=(
                f"{event_id} ({event.kind}) replayed over "
                f"{event.window.start}..{event.window.end}; {summary.landed} batches landed"
            ),
            sim_time=self._harness.clock.now,
            results=tuple(summary.results),
        )

    # ----------------------------------------------------------- 2. break feed --
    def break_feed(self, source_id: str) -> ControlOutcome:
        """Pause a feed. Nothing from it lands until :meth:`restore_feed`."""
        self._harness.pause(source_id)
        return ControlOutcome(
            control="break_feed",
            detail=f"{source_id} paused; its next scheduled drop will not arrive",
            sim_time=self._harness.clock.now,
            freshness=tuple(self._harness.freshness()),
        )

    def restore_feed(self, source_id: str) -> ControlOutcome:
        """Let a paused feed deliver again from the next scheduled drop."""
        self._harness.resume(source_id)
        return ControlOutcome(
            control="restore_feed",
            detail=f"{source_id} resumed",
            sim_time=self._harness.clock.now,
            freshness=tuple(self._harness.freshness()),
        )

    # ---------------------------------------------------------- 3. restatement --
    def send_restatement(self, source_id: str, period: str) -> ControlOutcome:
        """Re-drop one period, revised. Both versions remain queryable in bronze."""
        contract = self._harness.contracts.source(source_id)
        if not contract.restatement.expected:
            raise IngestionError(
                f"{source_id} does not restate",
                detail="only a source whose contract declares restatement may be re-dropped",
            )
        arrival = manual_arrival(source_id, (period,), self._harness.clock.now, is_restatement=True)
        frame = self._harness.slicer.slice(contract, arrival)
        if frame.empty:
            raise IngestionError(f"{source_id} has no rows for period {period!r}")
        revision = self._harness.runner.batch_registry.revisions_of(source_id, period) + 1
        revised = self._restater.revise(frame, contract, period, revision)
        self._harness.land_frame(
            arrival,
            revised,
            producer_note=f"{period} revised by the producer (revision {revision})",
        )
        results = self._harness.drain()
        return ControlOutcome(
            control="send_restatement",
            detail=f"{source_id} re-delivered {period} as revision {revision}",
            sim_time=self._harness.clock.now,
            results=tuple(results),
        )

    # ------------------------------------------------------------ 4. time travel --
    def time_travel(self, target: dt.date) -> ControlOutcome:
        """Move the clock and rebuild state to match.

        Forwards is a replay: everything due in between lands and is ingested.
        Backwards cannot be a replay — the warehouse already holds the future — so it
        is a reset followed by a bulk load to the target. That is slower and entirely
        deliberate: silently leaving future rows in the marts would make every number
        on screen a lie about the date in the corner.
        """
        zone = self._harness.clock.timezone
        moment = dt.datetime.combine(target, dt.time.min, zone)
        if moment > self._harness.clock.now:
            summary = self._harness.advance_to(moment)
            return self._travelled(target, summary, rebuilt=False)
        self.reset()
        summary = self._harness.backfill(self._horizon_start, target)
        return self._travelled(target, summary, rebuilt=True)

    def _travelled(
        self, target: dt.date, summary: ReplaySummary, *, rebuilt: bool
    ) -> ControlOutcome:
        how = "state rebuilt from the historical load" if rebuilt else "replayed forward"
        return ControlOutcome(
            control="time_travel",
            detail=f"clock at {target.isoformat()}; {how}; {summary.landed} batches landed",
            sim_time=self._harness.clock.now,
            results=tuple(summary.results),
        )

    # ------------------------------------------------------------------ reset --
    def reset(self) -> ControlOutcome:
        """Empty the warehouse and the landing zone. The rehearsal's starting state."""
        self._warehouse.drop_all()
        self._harness.runner.ensure_tables()
        self._harness.landing.clear()
        self._harness.watcher.rescan()
        for source_id in sorted(self._harness.paused_sources):
            self._harness.resume(source_id)
        logger.info("controls.reset", at=self._harness.clock.now.isoformat())
        return ControlOutcome(
            control="reset",
            detail="warehouse and landing zone cleared; every paused feed resumed",
            sim_time=self._harness.clock.now,
        )

    def _event(self, event_id: str):  # type: ignore[no-untyped-def]  # returns Event
        """Look up a ledger event, or fail with the injectable ids."""
        for event in self._ledger:
            if event.event_id == event_id:
                return event
        raise IngestionError(
            f"unknown event {event_id!r}",
            detail=f"injectable: {', '.join(self.injectable_events())}",
        )
