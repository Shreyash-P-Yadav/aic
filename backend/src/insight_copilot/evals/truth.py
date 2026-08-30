"""What the ledger says was really happening in a window — not in one event.

The backtest's first honest run scored 22% on "did the attribution name this event's
top region", flat across high, medium and low detectability. Flat is the tell: an
engine that is genuinely detecting something does better on the loud events than on
the quiet ones. Chance on five regions is 20%.

The cause was the question, not the engine. The calibration corpus plants events
densely — every covered day carries about eight live events — so the movement visible
in one event's window is the sum of that event and its neighbours. Asking "was *this*
event's region named" is unanswerable from the data the engine can see, and grading an
answerable system against an unanswerable question produces a calibration curve fitted
to noise, which is worse than no curve.

The answerable question, and the one an insight actually claims, is: **of everything
moving this window, was the segment the engine named the one that moved it most?** This
module computes that from the ledger — every event overlapping the window, weighted by
its own recorded isolated contribution, resolved to the region and category the ledger
recorded as each event's top member.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from insight_copilot.errors import StatisticalError

TRUTH_DIMENSIONS = ("region", "category")
"""The dimensions the ledger records a true top member for. Channel is not among them:
the generator plants no channel-scoped mechanism, so there is no channel truth to
grade against and claiming one would be inventing an answer key."""


@dataclass(frozen=True)
class WindowTruth:
    """The dominant segment of one window, and how dominant it was."""

    dominant: dict[str, str]
    share: dict[str, float]
    contributors: int
    total_weight: float

    def matches(self, dimension: str, member: str) -> bool:
        """Did a claim on ``dimension`` name the dominant member?"""
        return self.dominant.get(dimension) == member

    @property
    def is_decided(self) -> bool:
        """Is there a dominant member at all, or did the window carry nothing?"""
        return bool(self.dominant) and self.total_weight > 0.0


class LedgerTruth:
    """Window-level ground truth, assembled once from the ledger."""

    def __init__(self, ledger: pd.DataFrame) -> None:
        required = {
            "window_start",
            "window_end",
            "isolated_delta_inr",
            "true_top_region",
            "true_top_category",
        }
        missing = required - set(ledger.columns)
        if missing:
            raise StatisticalError(
                "the ledger is missing columns the backtest needs",
                detail=", ".join(sorted(missing)),
            )
        self._starts = pd.to_datetime(ledger["window_start"]).dt.date.to_numpy()
        self._ends = pd.to_datetime(ledger["window_end"]).dt.date.to_numpy()
        self._weights = ledger["isolated_delta_inr"].abs().to_numpy(dtype=float)
        self._members = {
            "region": ledger["true_top_region"].astype(str).to_numpy(),
            "category": ledger["true_top_category"].astype(str).to_numpy(),
        }

    def for_window(self, start: dt.date, end: dt.date) -> WindowTruth:
        """The dominant region and category over ``[start, end]``.

        Weighting is by ``isolated_delta_inr`` — the effect of that event *alone*,
        which is the only per-event quantity that adds across concurrent events
        without double-counting their interactions — **pro-rated to the days that
        actually overlap**. Without the pro-rating a six-month price change dominates
        every one-week window it touches purely because its total is large, and the
        answer key stops describing the week being graded.
        """
        overlaps = [
            index
            for index in range(len(self._weights))
            if self._starts[index] <= end and self._ends[index] >= start
        ]
        if not overlaps:
            return WindowTruth(dominant={}, share={}, contributors=0, total_weight=0.0)

        allocated = {index: self._overlap_weight(index, start, end) for index in overlaps}
        dominant: dict[str, str] = {}
        share: dict[str, float] = {}
        total = float(sum(allocated.values()))
        for dimension in TRUTH_DIMENSIONS:
            weights: dict[str, float] = defaultdict(float)
            for index in overlaps:
                weights[str(self._members[dimension][index])] += allocated[index]
            member = max(weights, key=lambda name: float(weights[name]))
            dominant[dimension] = member
            share[dimension] = weights[member] / total if total > 0.0 else 0.0
        return WindowTruth(
            dominant=dominant, share=share, contributors=len(overlaps), total_weight=total
        )

    def _overlap_weight(self, index: int, start: dt.date, end: dt.date) -> float:
        """One event's contribution pro-rated to the days inside ``[start, end]``.

        Uniform across the event's own window: the ledger records a total, not a daily
        profile, and inventing a shape for it would be making up an answer key.
        """
        event_start: dt.date = self._starts[index]
        event_end: dt.date = self._ends[index]
        event_days = (event_end - event_start).days + 1
        overlap_days = (min(event_end, end) - max(event_start, start)).days + 1
        weight = float(self._weights[index])
        return weight * max(overlap_days, 0) / max(event_days, 1)
