"""``SimClock`` — the only source of "now" anywhere downstream of generation.

WHY a simulated clock rather than ``datetime.now()``: the demo runs a 36-month world
against a fixed "today" (2026-03-29), and freshness, watermarks and abstention are
all functions of the gap between now and the last batch. If any component read the
wall clock, every one of those behaviours would drift with the calendar and the
scripted demo would decay into nonsense within a week.

Four modes, from the design's operating table:

* **backfill** — time is advanced explicitly by the caller. Deterministic; this is
  what the bulk historical load and every test use.
* **replay(N x)** — sim time runs at ``speed`` sim-seconds per wall-second from a
  go-live moment. The main demo: one sim-day every two seconds by default.
* **live(1 x)** — replay with ``speed = 1``. The long-running exhibit.
* **step** — one arrival at a time under manual control, for debugging and for a
  judge who wants to inspect each step.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from zoneinfo import ZoneInfo

from insight_copilot.config import ClockMode
from insight_copilot.errors import ConfigError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

DEFAULT_STEP = dt.timedelta(days=1)
"""One sim-day per manual step: the cadence of the daily feeds."""

WallClock = Callable[[], float]
"""A monotonic wall-time source in seconds. Injected so tests never sleep."""


class SimClock:
    """Simulated time, advanced by a mode-specific rule."""

    def __init__(
        self,
        *,
        start: dt.datetime,
        mode: ClockMode = "backfill",
        speed: float = 1.0,
        tz: str = "Asia/Kolkata",
        step_size: dt.timedelta = DEFAULT_STEP,
        wall: WallClock = time.monotonic,
    ) -> None:
        if speed <= 0.0:
            raise ConfigError(f"clock speed must be positive, got {speed}")
        self._zone = ZoneInfo(tz)
        if start.tzinfo is None:
            start = start.replace(tzinfo=self._zone)
        self._start = start.astimezone(self._zone)
        self._now = self._start
        self._mode: ClockMode = mode
        self._speed = 1.0 if mode == "live" else speed
        self._step_size = step_size
        self._wall = wall
        self._wall_origin = wall()

    # ------------------------------------------------------------------ read --
    @property
    def now(self) -> dt.datetime:
        """Current simulated time, always tz-aware in the house timezone."""
        return self._now

    @property
    def today(self) -> dt.date:
        """The simulated calendar date."""
        return self._now.date()

    @property
    def mode(self) -> ClockMode:
        """The operating mode this clock was built in."""
        return self._mode

    @property
    def speed(self) -> float:
        """Sim-seconds per wall-second. Always 1.0 in live mode."""
        return self._speed

    @property
    def step_size(self) -> dt.timedelta:
        """How far one manual step advances. One sim-day by default."""
        return self._step_size

    @property
    def timezone(self) -> ZoneInfo:
        """The house timezone. Every timestamp this clock hands out carries it."""
        return self._zone

    # --------------------------------------------------------------- advance --
    def sync(self) -> dt.datetime:
        """Pull sim time forward from the wall clock. No-op outside replay/live.

        Called by the harness loop rather than by ``now``, so that a single tick of
        the pipeline sees one consistent instant rather than a time that creeps
        between two reads of the same expression.
        """
        if self._mode in ("replay", "live"):
            elapsed = self._wall() - self._wall_origin
            self._now = self._start + dt.timedelta(seconds=elapsed * self._speed)
        return self._now

    def advance(self, delta: dt.timedelta) -> dt.datetime:
        """Move sim time forward by ``delta``. Rejects a negative delta."""
        if delta < dt.timedelta(0):
            raise ConfigError(f"advance requires a non-negative delta, got {delta}")
        self._now = self._now + delta
        return self._now

    def step(self) -> dt.datetime:
        """Advance exactly one step. The manual control behind step mode."""
        return self.advance(self._step_size)

    def travel_to(self, moment: dt.datetime) -> dt.datetime:
        """Jump to any instant, forwards or backwards — the demo's time-travel button.

        Rewinding is legal here and nowhere else: state rebuild after a jump is the
        caller's job, and a clock that silently refused to go back would turn that
        control into a no-op the presenter discovers on stage.
        """
        target = moment if moment.tzinfo else moment.replace(tzinfo=self._zone)
        target = target.astimezone(self._zone)
        logger.info(
            "clock.travel", frm=self._now.isoformat(), to=target.isoformat(), mode=self._mode
        )
        self._now = target
        self._wall_origin = self._wall()
        self._start = target
        return self._now

    def reset(self) -> dt.datetime:
        """Return to the moment this clock was constructed at."""
        self._now = self._start
        self._wall_origin = self._wall()
        return self._now

    # ------------------------------------------------------------------ util --
    def localise(self, moment: dt.datetime) -> dt.datetime:
        """Attach or convert to the house timezone, for values crossing a boundary."""
        return (
            moment.replace(tzinfo=self._zone)
            if moment.tzinfo is None
            else moment.astimezone(self._zone)
        )

    def __repr__(self) -> str:
        return f"SimClock(mode={self._mode!r}, now={self._now.isoformat()}, speed={self._speed})"
