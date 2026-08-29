"""Cutting the world into batches: what would this source have exported *this time*?

The generated source frames (P4) hold the whole 36 months as one table each. A real
feed never delivers that; it delivers the slice its contract's ``covers`` block
describes. This module is the only place that translates a planned arrival into rows,
and it reads the contract's ``watermark`` column rather than knowing anything about
individual sources.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.datagen.projection.base import SourceFrames
from insight_copilot.errors import IngestionError
from insight_copilot.harness.periods import label_start
from insight_copilot.harness.scheduler import PlannedArrival

WEEK_LABEL_COLUMN = "iso_week"
"""Weekly feeds carry their period label as a delivered column, so a week slice is a
membership test rather than a date range. Both weekly contracts declare it as their
watermark, which is what makes this generic rather than a special case."""


class PeriodSlicer:
    """Selects the rows one planned arrival delivers, from the generated world."""

    def __init__(self, frames: SourceFrames) -> None:
        self._frames = frames

    def slice(self, contract: SourceContract, arrival: PlannedArrival) -> pd.DataFrame:
        """The rows this batch carries. May legitimately be empty (a silent gap)."""
        if contract.source_id not in self._frames:
            raise IngestionError(f"no generated rows for source {contract.source_id!r}")
        frame = self._frames[contract.source_id]
        period = contract.covers.period
        if period == "static":
            return frame.copy()
        if period == "previous_iso_week":
            return self._by_week(frame, arrival.periods)
        if period == "continuous":
            return self._by_window(frame, contract, arrival)
        return self._by_day(frame, contract, arrival.periods)

    # ------------------------------------------------------------- strategies --
    @staticmethod
    def _by_week(frame: pd.DataFrame, periods: tuple[str, ...]) -> pd.DataFrame:
        """Weekly feeds: membership on the delivered ISO-week label."""
        if WEEK_LABEL_COLUMN not in frame.columns:
            raise IngestionError(f"weekly source lacks a {WEEK_LABEL_COLUMN!r} column")
        return frame.loc[frame[WEEK_LABEL_COLUMN].isin(periods)].copy()

    @staticmethod
    def _by_day(
        frame: pd.DataFrame, contract: SourceContract, periods: tuple[str, ...]
    ) -> pd.DataFrame:
        """Daily feeds: the watermark date falls inside one of the covered days."""
        column = contract.watermark
        days = {label_start(label) for label in periods}
        stamps = pd.to_datetime(frame[column]).dt.date
        return frame.loc[stamps.isin(days)].copy()

    @staticmethod
    def _by_window(
        frame: pd.DataFrame, contract: SourceContract, arrival: PlannedArrival
    ) -> pd.DataFrame:
        """Continuous feeds: everything with a watermark since the previous firing.

        A restating continuous source also re-sends its lookback window, because its
        revisions arrive as newer rows for the same business key rather than as a
        superseding period. That is why ``window_days`` widens the slice here and the
        period tuple elsewhere.
        """
        column = contract.watermark
        upper = arrival.scheduled_at
        lower = arrival.covers_from or (upper - dt.timedelta(days=1))
        if contract.restatement.expected:
            lower = lower - dt.timedelta(days=contract.restatement.window_days)
        stamps = pd.to_datetime(frame[column])
        # The delivered timestamps are naive local values; the schedule is tz-aware.
        # Comparing them requires dropping the offset, not converting it: a feed that
        # stamps the wrong zone (P9) must still be sliced by what it actually wrote.
        low = pd.Timestamp(lower.replace(tzinfo=None))
        high = pd.Timestamp(upper.replace(tzinfo=None))
        return frame.loc[(stamps > low) & (stamps <= high)].copy()
