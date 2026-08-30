""" "Have we seen this before?" — nearest neighbours over past insights.

The most useful thing a system can tell an analyst about a new movement is often not
a p-value but *"this looks like the DC-North pick failure in March; that one took
eleven days to clear and the fix was reallocating volume to DC-West"*. That is a
retrieval problem over a small structured space, not a semantic one, so it is solved
with an explicit distance over the fields that make two movements comparable rather
than with an embedding model this build is not permitted to require.

Distance is deliberately interpretable. Every term is bounded to [0, 1], every weight
is named, and :meth:`CaseLibrary.similar` returns the per-term distances so the UI can
say *why* two cases were called alike. A similarity a reader cannot interrogate is a
similarity they will (rightly) ignore.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from insight_copilot.logging import get_logger

logger = get_logger(__name__)

SEGMENT_WEIGHT = 0.40
"""Same place is the strongest signal that two movements are the same kind of thing."""

DIRECTION_WEIGHT = 0.20
"""A drop and a spike of the same size are not the same case."""

MAGNITUDE_WEIGHT = 0.25
"""Compared in log space, so 2% against 4% is the same distance as 20% against 40%."""

SEASON_WEIGHT = 0.15
"""Circular distance in the year. A festive-quarter movement resembles other festive
-quarter movements more than it resembles an identical movement in June."""

MAGNITUDE_SCALE = 2.0
"""Log-ratio at which two magnitudes count as maximally different (a factor of ~7)."""

DAYS_IN_YEAR = 365.25


@dataclass(frozen=True)
class Case:
    """One past movement, as the library stores it."""

    insight_id: str
    kpi_id: str
    day: dt.date
    delta_pct: float
    segment: str
    cause: str = ""
    resolution: str = ""
    days_to_resolve: int | None = None

    @property
    def direction(self) -> int:
        """-1 for a fall, +1 for a rise."""
        return -1 if self.delta_pct < 0 else 1


@dataclass(frozen=True)
class Neighbour:
    """One retrieved case with its distance broken out by term."""

    case: Case
    distance: float
    terms: dict[str, float] = field(default_factory=dict)

    @property
    def similarity(self) -> float:
        """1 - distance, for a reader who prefers "how alike"."""
        return 1.0 - self.distance

    @property
    def detail(self) -> str:
        """Why these two were called alike, in the order the terms contributed."""
        ordered = sorted(self.terms.items(), key=lambda item: item[1])
        return "; ".join(f"{name} {1.0 - value:.0%} alike" for name, value in ordered)


class CaseLibrary:
    """A small, interpretable nearest-neighbour index over resolved movements."""

    def __init__(self, cases: list[Case] | None = None) -> None:
        self._cases: list[Case] = list(cases or [])

    def __len__(self) -> int:
        return len(self._cases)

    @property
    def cases(self) -> list[Case]:
        """Every stored case, in insertion order."""
        return list(self._cases)

    def add(self, case: Case) -> Case:
        """File one resolved movement. Re-filing the same id replaces it."""
        self._cases = [item for item in self._cases if item.insight_id != case.insight_id]
        self._cases.append(case)
        return case

    def similar(self, query: Case, *, limit: int = 3, same_kpi: bool = True) -> list[Neighbour]:
        """The closest past movements, nearest first, never including the query itself."""
        pool = [
            item
            for item in self._cases
            if item.insight_id != query.insight_id and (not same_kpi or item.kpi_id == query.kpi_id)
        ]
        neighbours = []
        for item in pool:
            distance, terms = _distance(query, item)
            neighbours.append(Neighbour(case=item, distance=distance, terms=terms))
        neighbours.sort(key=lambda item: (item.distance, item.case.insight_id))
        logger.info("learning.cases_retrieved", pool=len(pool), returned=min(limit, len(pool)))
        return neighbours[:limit]


def _distance(left: Case, right: Case) -> tuple[float, dict[str, float]]:
    """The weighted distance and its terms. Pure: two cases in, numbers out."""
    segment = 0.0 if left.segment == right.segment else 1.0
    direction = 0.0 if left.direction == right.direction else 1.0
    magnitude = _magnitude_distance(left.delta_pct, right.delta_pct)
    season = _season_distance(left.day, right.day)
    terms = {
        "segment": segment,
        "direction": direction,
        "magnitude": magnitude,
        "season": season,
    }
    total = (
        SEGMENT_WEIGHT * segment
        + DIRECTION_WEIGHT * direction
        + MAGNITUDE_WEIGHT * magnitude
        + SEASON_WEIGHT * season
    )
    return float(total), terms


def _magnitude_distance(left: float, right: float) -> float:
    """Log-ratio distance, bounded to [0, 1]. Zero magnitudes are maximally far."""
    import math

    a, b = abs(left), abs(right)
    if a <= 0.0 or b <= 0.0:
        return 1.0 if a != b else 0.0
    return float(min(abs(math.log(a / b)) / MAGNITUDE_SCALE, 1.0))


def _season_distance(left: dt.date, right: dt.date) -> float:
    """Circular distance in the year, bounded to [0, 1].

    Circular because 28 December and 3 January are four days apart, not 360.
    """
    gap = abs(left.timetuple().tm_yday - right.timetuple().tm_yday)
    return float(min(gap, DAYS_IN_YEAR - gap) / (DAYS_IN_YEAR / 2.0))
