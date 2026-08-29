"""The single seam through which an event may perturb the simulation.

Every event effect enters here and nowhere else. That is what makes the windowed
counterfactual honest: "re-run without event E" is implemented by handing the
simulator a different overlay, with **no other difference at all** — same seeds, same
decisions, same code path.

The identity effect is exact. A multiplier of ``1.0`` and an addend of ``0.0`` are
exact in IEEE-754, so a zero-magnitude event produces bit-identical output to no
event. The P2 determinism gate asserts precisely that, and it is the test everything
downstream depends on: if it fails, the RNG is positional somewhere and every
ground-truth number in the submission is fiction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DayEffects:
    """What events do to one simulated day. ``None`` means "no effect", not "identity".

    Distinguishing ``None`` from an all-ones array matters for speed — most days have
    no events at all, and skipping the multiply keeps the day loop tight — but the
    two must be numerically indistinguishable, which the determinism test checks.
    """

    availability_cap: np.ndarray | None = None
    """``(n_warehouses, n_skus)`` in [0, 1]: a ceiling on the fraction of the day's
    DEMAND this warehouse can pick and ship.

    A throughput cap, not a stock cap. A conveyor failure does not consume inventory;
    it limits how many units per day can move through the building. Capping a
    fraction of *on-hand* would be inert at any normal level of cover — five weeks of
    stock at 48% is still two and a half weeks of pickable units — which is precisely
    the bug this wording exists to prevent."""

    price_multiplier: np.ndarray | None = None
    """``(n_skus, n_regions)`` multiplier on the effective selling price."""

    media_multiplier: np.ndarray | None = None
    """``(n_media_channels,)`` multiplier on that day's share of weekly spend."""

    demand_multiplier: np.ndarray | None = None
    """``(n_skus, n_regions, n_channels)`` multiplier on latent demand — competitor
    actions and category shocks, which move demand without moving our own levers."""

    bulk_units: np.ndarray | None = None
    """``(n_skus, n_regions, n_channels)`` additive units. A one-off institutional
    order is a data event, not a trend, and the engine must say so."""

    @property
    def is_empty(self) -> bool:
        """True when this day has no event effects at all."""
        return all(
            field is None
            for field in (
                self.availability_cap,
                self.price_multiplier,
                self.media_multiplier,
                self.demand_multiplier,
                self.bulk_units,
            )
        )


EMPTY_DAY = DayEffects()
"""Shared singleton for the overwhelming majority of days."""


class EventOverlay(ABC):
    """Supplies per-day event effects to the simulator."""

    @abstractmethod
    def effects_on(self, day_index: int) -> DayEffects:
        """Effects for the day at ``day_index`` offset from the horizon start."""

    @abstractmethod
    def describe(self) -> str:
        """One line naming what this overlay contains, for the run log."""


class NoEvents(EventOverlay):
    """The counterfactual baseline: a world in which nothing happened."""

    def effects_on(self, day_index: int) -> DayEffects:  # noqa: ARG002 - ABC signature
        """Always empty."""
        return EMPTY_DAY

    def describe(self) -> str:
        """Name this overlay for the run log."""
        return "no events"


class CompositeOverlay(EventOverlay):
    """Combines several overlays multiplicatively.

    Used to hold the scenario, ambient and calibration event sets side by side, and
    to build the Shapley subsets in P3 by dropping members.
    """

    def __init__(self, overlays: list[EventOverlay]) -> None:
        self._overlays = list(overlays)

    def effects_on(self, day_index: int) -> DayEffects:
        """Multiply multipliers, sum addends, take the minimum of availability caps."""
        parts = [
            effects
            for overlay in self._overlays
            if not (effects := overlay.effects_on(day_index)).is_empty
        ]
        if not parts:
            return EMPTY_DAY
        if len(parts) == 1:
            return parts[0]
        return DayEffects(
            availability_cap=_reduce(parts, "availability_cap", np.minimum),
            price_multiplier=_reduce(parts, "price_multiplier", np.multiply),
            media_multiplier=_reduce(parts, "media_multiplier", np.multiply),
            demand_multiplier=_reduce(parts, "demand_multiplier", np.multiply),
            bulk_units=_reduce(parts, "bulk_units", np.add),
        )

    def describe(self) -> str:
        """Name every contained overlay."""
        return " + ".join(overlay.describe() for overlay in self._overlays)


def _reduce(parts: list[DayEffects], field: str, combine: np.ufunc) -> np.ndarray | None:
    """Combine one field across overlays, ignoring those that do not set it."""
    arrays = [array for part in parts if (array := getattr(part, field)) is not None]
    if not arrays:
        return None
    result: np.ndarray = arrays[0]
    for array in arrays[1:]:
        result = np.asarray(combine(result, array))
    return result
