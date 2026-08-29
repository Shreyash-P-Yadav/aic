"""A five-field cron evaluator, because arrival schedules live in source contracts.

WHY a hand-rolled parser rather than a dependency: the pinned stack has no cron
library, and the subset the source contracts actually use is small and fully
specified — ``*``, ``a``, ``a-b``, ``a,b``, ``*/n`` and ``a-b/n`` over the standard
five fields. Fifty lines of parsing is a smaller liability than a package whose
day-of-week convention we would have to verify anyway.

Semantics follow POSIX cron, including the one surprising rule: when **both**
day-of-month and day-of-week are restricted the schedule fires when *either*
matches. None of the shipped contracts restricts both, but silently getting this
wrong for a future contract would be an arrival that never happens.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from insight_copilot.errors import ContractError

_FIELD_RANGES: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day_of_month", 1, 31),
    ("month", 1, 12),
    ("day_of_week", 0, 6),
)

MAX_LOOKAHEAD_DAYS = 400
"""A schedule that matches no day inside a leap year plus a month is malformed.
Bounding the search turns an impossible cron into an error rather than a hang."""


def _parse_field(spec: str, name: str, low: int, high: int) -> frozenset[int]:
    """Expand one cron field into the set of values it matches."""
    values: set[int] = set()
    for part in spec.split(","):
        step = 1
        body = part
        if "/" in part:
            body, _, step_text = part.partition("/")
            try:
                step = int(step_text)
            except ValueError as exc:
                raise ContractError(f"cron {name}: bad step in {part!r}") from exc
            if step < 1:
                raise ContractError(f"cron {name}: step must be positive in {part!r}")
        if body in ("*", ""):
            start, stop = low, high
        elif "-" in body:
            start_text, _, stop_text = body.partition("-")
            start, stop = _int(start_text, name), _int(stop_text, name)
        else:
            start = stop = _int(body, name)
        # Day-of-week 7 is Sunday in the common extension; fold it onto 0 so the
        # matcher only ever deals with the documented 0-6 range.
        if name == "day_of_week":
            start, stop = start % 7, stop % 7
            if start > stop:
                raise ContractError(f"cron {name}: descending range {part!r}")
        if start < low or stop > high or start > stop:
            raise ContractError(f"cron {name}: {part!r} outside {low}-{high}")
        values.update(range(start, stop + 1, step))
    if not values:
        raise ContractError(f"cron {name}: {spec!r} matches nothing")
    return frozenset(values)


def _int(text: str, name: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise ContractError(f"cron {name}: {text!r} is not an integer") from exc


@dataclass(frozen=True)
class CronSchedule:
    """A parsed five-field cron expression, evaluated in a caller-supplied tz."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    dom_restricted: bool
    dow_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> CronSchedule:
        """Parse ``"0 6 * * 1"``. Raises ``ContractError`` on anything malformed."""
        parts = expression.split()
        if len(parts) != len(_FIELD_RANGES):
            raise ContractError(
                f"cron must have 5 fields, got {len(parts)}", detail=repr(expression)
            )
        expanded = [
            _parse_field(part, name, low, high)
            for part, (name, low, high) in zip(parts, _FIELD_RANGES, strict=True)
        ]
        return cls(
            minutes=expanded[0],
            hours=expanded[1],
            days_of_month=expanded[2],
            months=expanded[3],
            days_of_week=expanded[4],
            dom_restricted=parts[2] != "*",
            dow_restricted=parts[4] != "*",
        )

    # ------------------------------------------------------------------ match --
    def _day_matches(self, day: dt.date) -> bool:
        """POSIX day rule: OR when both day fields are restricted, AND otherwise."""
        if day.month not in self.months:
            return False
        # ``isoweekday()`` is Mon=1..Sun=7; cron is Sun=0..Sat=6.
        dow = day.isoweekday() % 7
        in_dom = day.day in self.days_of_month
        in_dow = dow in self.days_of_week
        if self.dom_restricted and self.dow_restricted:
            return in_dom or in_dow
        return in_dom and in_dow

    def matches(self, moment: dt.datetime) -> bool:
        """Does this schedule fire at ``moment`` (to the minute)?"""
        return (
            moment.minute in self.minutes
            and moment.hour in self.hours
            and self._day_matches(moment.date())
        )

    @property
    def _minutes_of_day(self) -> list[int]:
        """Sorted minutes-past-midnight this schedule fires at, on a matching day."""
        return sorted(hour * 60 + minute for hour in self.hours for minute in self.minutes)

    # ------------------------------------------------------------------- walk --
    def next_after(self, moment: dt.datetime) -> dt.datetime:
        """The first firing strictly after ``moment``, preserving its tzinfo.

        Days are scanned first and minutes only within a matching day, so an annual
        schedule costs ~366 date checks rather than half a million minute checks.
        """
        cursor = moment.replace(second=0, microsecond=0)
        offsets = self._minutes_of_day
        for day_index in range(MAX_LOOKAHEAD_DAYS + 1):
            day = (cursor + dt.timedelta(days=day_index)).date()
            if not self._day_matches(day):
                continue
            midnight = dt.datetime.combine(day, dt.time.min, tzinfo=moment.tzinfo)
            for offset in offsets:
                candidate = midnight + dt.timedelta(minutes=offset)
                if candidate > moment:
                    return candidate
        raise ContractError(
            "cron matched no firing within the lookahead",
            detail=f"{MAX_LOOKAHEAD_DAYS} days after {moment.isoformat()}",
        )

    def previous_before(self, moment: dt.datetime) -> dt.datetime:
        """The last firing strictly before ``moment``. Used to bound a continuous feed."""
        cursor = moment.replace(second=0, microsecond=0)
        offsets = list(reversed(self._minutes_of_day))
        for day_index in range(MAX_LOOKAHEAD_DAYS + 1):
            day = (cursor - dt.timedelta(days=day_index)).date()
            if not self._day_matches(day):
                continue
            midnight = dt.datetime.combine(day, dt.time.min, tzinfo=moment.tzinfo)
            for offset in offsets:
                candidate = midnight + dt.timedelta(minutes=offset)
                if candidate < moment:
                    return candidate
        raise ContractError(
            "cron matched no firing within the lookback",
            detail=f"{MAX_LOOKAHEAD_DAYS} days before {moment.isoformat()}",
        )

    def between(self, start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
        """Every firing in the half-open interval ``(start, end]``."""
        firings: list[dt.datetime] = []
        cursor = start
        while True:
            cursor = self.next_after(cursor)
            if cursor > end:
                return firings
            firings.append(cursor)
