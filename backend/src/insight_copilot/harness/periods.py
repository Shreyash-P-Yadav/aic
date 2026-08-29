"""Period labels: the vocabulary batches, watermarks and supersession all speak.

A *period* is the unit of data a batch claims to describe. It has to be a single
string because it is a partition-directory name, a manifest field, a watermark key
and a supersession key all at once — and because "recompute exactly the affected
window" is only expressible if two batches can be compared for covering the same
thing.

Three label shapes, one per grain the shipped contracts use:

* ``2026-03-08``  — a calendar day (``previous_day``, ``t_minus_2``, ``continuous``)
* ``2026-W11``    — an ISO week (``previous_iso_week``)
* ``static``      — a reference table that has no period at all

WHY ``continuous`` feeds get a day label rather than no label: a ticket feed that
lands every thirty minutes still has to be recomputable "for Tuesday", and the
freshness tracker has to be able to say which day is complete. The label names the
day the batch was cut on; the rows inside it are bounded by the previous firing.
"""

from __future__ import annotations

import datetime as dt
import re

from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.errors import ContractError

STATIC_PERIOD = "static"
"""The single period of a reference table. It is never superseded by date."""

DAY_LABEL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEK_LABEL = re.compile(r"^\d{4}-W\d{2}$")

T_MINUS_2_DAYS = 2
"""The WMS extract describes the day before yesterday, by design, not by accident."""


def day_label(day: dt.date) -> str:
    """``2026-03-08``."""
    return day.isoformat()


def week_label(day: dt.date) -> str:
    """The ISO week label containing ``day``, e.g. ``2026-W11``."""
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_start(label: str) -> dt.date:
    """Monday of an ISO week label. Inverse of :func:`week_label`."""
    year, _, week = label.partition("-W")
    return dt.date.fromisocalendar(int(year), int(week), 1)


def label_start(label: str) -> dt.date:
    """The first calendar day a label covers. ``static`` has no start."""
    if DAY_LABEL.match(label):
        return dt.date.fromisoformat(label)
    if WEEK_LABEL.match(label):
        return week_start(label)
    raise ContractError(f"not a dated period label: {label!r}")


def label_end(label: str) -> dt.date:
    """The last calendar day a label covers, inclusive."""
    start = label_start(label)
    return start + dt.timedelta(days=6) if WEEK_LABEL.match(label) else start


def is_dated(label: str) -> bool:
    """Can this label be placed on a calendar? ``static`` cannot."""
    return bool(DAY_LABEL.match(label) or WEEK_LABEL.match(label))


def periods_for(contract: SourceContract, scheduled_at: dt.datetime) -> tuple[str, ...]:
    """The periods one batch of ``contract`` covers, newest first.

    Restatement widens this tuple for *periodic* sources only: a weekly feed with a
    fourteen-day restatement window re-sends the two weeks behind the one it is
    reporting, which is exactly the three-week ``covers.periods`` in the design's
    manifest example. A ``continuous`` feed has no discrete prior period to supersede
    — its revisions arrive as newer rows for the same business key — so its window
    widens the row slice instead of the label tuple.
    """
    day = scheduled_at.date()
    period = contract.covers.period
    if period == "static":
        return (STATIC_PERIOD,)
    if period == "previous_iso_week":
        latest = week_label(day - dt.timedelta(days=7))
        extra = contract.restatement.window_days // 7 if contract.restatement.expected else 0
        return tuple(
            week_label(week_start(latest) - dt.timedelta(days=7 * back))
            for back in range(extra + 1)
        )
    if period == "previous_day":
        return (day_label(day - dt.timedelta(days=1)),)
    if period == "t_minus_2":
        return (day_label(day - dt.timedelta(days=T_MINUS_2_DAYS)),)
    if period == "previous_month":
        first_of_month = day.replace(day=1)
        return (day_label(first_of_month - dt.timedelta(days=1)),)
    return (day_label(day),)


def affected_days(periods: tuple[str, ...]) -> list[dt.date]:
    """Every calendar day the periods touch — the window a recompute must cover."""
    days: set[dt.date] = set()
    for label in periods:
        if not is_dated(label):
            continue
        cursor, last = label_start(label), label_end(label)
        while cursor <= last:
            days.add(cursor)
            cursor += dt.timedelta(days=1)
    return sorted(days)
