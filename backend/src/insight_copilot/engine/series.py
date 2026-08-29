"""The one shape every statistical routine in the engine consumes.

A ``Series`` is a date axis and a value axis of the same length, sorted, with no
duplicate dates and no gaps. Enforcing that here rather than in each routine is what
lets every function below be a pure array transform: a seasonal decomposition that
silently receives a gapped series does not fail, it returns a wrong period, and that
error would propagate all the way to a narrated sentence.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.errors import StatisticalError

MIN_POSITIVE = 1e-9
"""Guard for the log transform. A KPI at exactly zero is a real observation; taking
its log is not, so the transform is only offered where every value clears this."""


@dataclass(frozen=True)
class Series:
    """A contiguous daily series of one measure at one grain."""

    dates: np.ndarray
    values: np.ndarray
    name: str = "value"

    def __post_init__(self) -> None:
        if self.dates.shape != self.values.shape:
            raise StatisticalError(
                f"{self.name}: axes disagree",
                detail=f"{self.dates.shape} dates against {self.values.shape} values",
            )
        if self.dates.size and not np.all(self.dates[1:] > self.dates[:-1]):
            raise StatisticalError(f"{self.name}: dates are not strictly increasing")

    def __len__(self) -> int:
        return int(self.values.size)

    @classmethod
    def from_frame(
        cls, frame: pd.DataFrame, *, date_column: str, value_column: str, fill: float | None = 0.0
    ) -> Series:
        """Build a gap-free daily series from a query result.

        ``fill`` is the value a missing day takes. Zero is right for an additive
        measure (no sales row means no revenue) and ``None`` is right for a ratio,
        where an absent day is genuinely unknown rather than zero.
        """
        if frame.empty:
            return cls(np.array([], dtype="datetime64[D]"), np.array([]), value_column)
        working = frame[[date_column, value_column]].copy()
        working[date_column] = pd.to_datetime(working[date_column])
        totals = working.groupby(date_column, observed=True)[value_column].sum().sort_index()
        spine = pd.date_range(totals.index.min(), totals.index.max(), freq="D")
        aligned = totals.reindex(spine)
        if fill is not None:
            aligned = aligned.fillna(fill)
        return cls(
            dates=aligned.index.to_numpy(dtype="datetime64[D]"),
            values=aligned.to_numpy(dtype=np.float64),
            name=value_column,
        )

    # ----------------------------------------------------------------- windows --
    def index_of(self, day: dt.date) -> int:
        """Position of a calendar day, or ``-1`` when it is outside the series."""
        target = np.datetime64(day, "D")
        found = np.searchsorted(self.dates, target)
        if found >= self.dates.size or self.dates[found] != target:
            return -1
        return int(found)

    def mask_between(self, start: dt.date, end: dt.date) -> np.ndarray:
        """Boolean mask of the inclusive date window."""
        return (self.dates >= np.datetime64(start, "D")) & (self.dates <= np.datetime64(end, "D"))

    def window(self, start: dt.date, end: dt.date) -> Series:
        """The inclusive sub-series between two dates."""
        mask = self.mask_between(start, end)
        return Series(self.dates[mask], self.values[mask], self.name)

    def exclude(self, mask: np.ndarray) -> Series:
        """The series with ``mask`` removed. Used to hold out an event window."""
        return Series(self.dates[~mask], self.values[~mask], self.name)

    # -------------------------------------------------------------- transforms --
    @property
    def strictly_positive(self) -> bool:
        """Can this series be modelled in logs?"""
        return bool(self.values.size) and bool(np.all(self.values > MIN_POSITIVE))

    def log(self) -> np.ndarray:
        """``log(y)``. Raises rather than clipping: a silent clip is a silent bias."""
        if not self.strictly_positive:
            raise StatisticalError(
                f"{self.name}: cannot take logs of a series with non-positive values",
                detail=f"minimum {float(self.values.min()) if self.values.size else 'n/a'}",
            )
        logged: np.ndarray = np.log(self.values)
        return logged

    @property
    def day_of_week(self) -> np.ndarray:
        """Monday = 0. Used to stratify the variance floor."""
        weekday: np.ndarray = (
            (self.dates.astype("datetime64[D]").astype(np.int64) + 3) % 7
        ).astype(np.int64)
        return weekday

    def as_dates(self) -> list[dt.date]:
        """The date axis as Python dates, for reporting."""
        return [day.astype(object) for day in self.dates]
