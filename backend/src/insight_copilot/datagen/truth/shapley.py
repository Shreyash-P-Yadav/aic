"""Shapley values over event subsets, for events whose effects interact.

**Why Shapley rather than one-at-a-time deltas.** When three events overlap, dropping
each in turn gives three numbers that do not sum to the observed gap, because the
events interact — a stockout suppresses exactly the volume a marketing cut would
otherwise have removed, so the two together cost less than the sum of their parts.
One-at-a-time deltas leave an interaction residual with nowhere to go.

The Shapley value is each event's average marginal contribution across all orderings.
Two properties earn it its place here:

* It is **exact, additive and order-independent** — the contributions sum to the
  total movement with no residual to explain away.
* It is **philosophically consistent with the engine's own method.** The Bennet
  decomposition in the attribution ladder is chosen precisely because it is symmetric
  and order-independent. Scoring a symmetric estimator against a symmetric ground
  truth is coherent; scoring it against one-at-a-time deltas would penalise it for
  interactions it correctly shares out.

The arithmetic is separated from the simulation. :func:`coalition_keys` says which
worlds are needed, :func:`shapley_from_values` turns their values into contributions,
and :func:`shapley_contributions` is the convenience wrapper that does both. The
separation is what lets the full-ledger job read each world's scalar and drop the
world immediately — 149 simulated panels would be about 25 GB held at once.

Cost is `2**n` worlds for a group of `n`. Groups larger than `MAX_SHAPLEY_EVENTS`
fall back to one-at-a-time deltas with the residual reported honestly rather than
hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import factorial
from typing import Protocol

from insight_copilot.datagen.events.models import Event
from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

MAX_SHAPLEY_EVENTS = 5
"""Beyond this, 2**n worlds stops being affordable.

n=5 is 32 worlds; n=6 would be 64 and n=8 would be 256. Five covers the scenario
ledger's single interacting cluster, and the calibration corpus is generated in
non-interacting lanes so its groups stay small.
"""


class ValueFn(Protocol):
    """A simulated world in, a scalar out — the coalition value function."""

    def __call__(self, panel: SimulationPanel) -> float: ...


class WorldSource(Protocol):
    """Supplies the world with a given set of events removed."""

    def without(self, removed: set[str]) -> SimulationPanel: ...


@dataclass(frozen=True)
class ShapleyResult:
    """Per-event contributions plus the total they are guaranteed to sum to."""

    contributions: dict[str, float]
    total: float
    method: str
    n_runs: int
    residual: float

    @property
    def sums_to_total(self) -> bool:
        """Exact for the Shapley path, up to floating point."""
        return abs(sum(self.contributions.values()) - self.total) < max(
            1e-6, 1e-9 * abs(self.total)
        )


def coalition_keys(ids: tuple[str, ...]) -> list[frozenset[str]]:
    """Every present-set whose value this group needs.

    Separated from the arithmetic so a caller can simulate the coalitions once,
    read each world's scalar, and discard the world before the next one is built.
    """
    if len(ids) <= MAX_SHAPLEY_EVENTS:
        return [
            frozenset(present)
            for size in range(len(ids) + 1)
            for present in combinations(ids, size)
        ]
    everything = frozenset(ids)
    return [everything, frozenset(), *(everything - {event_id} for event_id in ids)]


def shapley_from_values(ids: tuple[str, ...], values: dict[frozenset[str], float]) -> ShapleyResult:
    """Shapley values from an already-computed coalition value table.

    Pure arithmetic: no simulation, no I/O. The coalition value of a subset S is
    ``v(S) - v(empty)`` — what the world is worth with exactly the events in S present.
    """
    n = len(ids)
    if n > MAX_SHAPLEY_EVENTS:
        return _one_at_a_time(ids, values)

    total = values[frozenset(ids)] - values[frozenset()]
    contributions: dict[str, float] = {}
    for event_id in ids:
        others = [other for other in ids if other != event_id]
        contribution = 0.0
        for size in range(n):
            # Shapley weight: |S|! (n-|S|-1)! / n! — the fraction of orderings in
            # which exactly this coalition precedes the event.
            weight = factorial(size) * factorial(n - size - 1) / factorial(n)
            for subset in combinations(others, size):
                without_event = frozenset(subset)
                contribution += weight * (
                    values[without_event | {event_id}] - values[without_event]
                )
        contributions[event_id] = contribution

    return ShapleyResult(
        contributions=contributions,
        total=total,
        method="shapley_within_window",
        n_runs=2**n,
        residual=total - sum(contributions.values()),
    )


def _one_at_a_time(ids: tuple[str, ...], values: dict[frozenset[str], float]) -> ShapleyResult:
    """Fallback for large groups: marginal deltas with the residual reported.

    Never silently absorbed into a contribution — an unexplained remainder that is
    labelled is honest, and one that is redistributed is not.
    """
    everything = frozenset(ids)
    full = values[everything]
    total = full - values[frozenset()]
    contributions = {event_id: full - values[everything - {event_id}] for event_id in ids}
    return ShapleyResult(
        contributions=contributions,
        total=total,
        method="one_at_a_time",
        n_runs=len(ids) + 2,
        residual=total - sum(contributions.values()),
    )


def shapley_contributions(
    *, runner: WorldSource, events: tuple[Event, ...], value_of: ValueFn
) -> ShapleyResult:
    """Simulate a group's coalitions and return its Shapley values.

    Convenience wrapper for callers with a handful of events. The ledger writer uses
    :func:`coalition_keys` and :func:`shapley_from_values` directly so it can share
    simulation runs across groups.
    """
    ids = tuple(event.event_id for event in events)
    everything = set(ids)
    values = {key: value_of(runner.without(everything - key)) for key in coalition_keys(ids)}
    result = shapley_from_values(ids, values)
    logger.info("truth.shapley", events=len(ids), runs=result.n_runs)
    return result
