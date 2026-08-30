"""Tier boundaries **derived from the fitted reliability curve**, never chosen by hand.

A tier is a promise about how often the system is right when it speaks in that tier.
Picking 0.9 for "High" because it is a round number makes the promise arbitrary; the
honest construction is the inverse — state the hit rate each tier is claiming, then ask
the fitted isotonic map which calibrated score first delivers it.

The contract still has the last word downward: ``abstain_below`` is a floor the curve
cannot argue past, because a KPI's owner is entitled to demand more caution than the
backtest alone would justify. It has no word upward, because a contract cannot grant
a confidence the data has not shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from insight_copilot.contracts.governance import ConfidencePolicy
from insight_copilot.engine.confidence import Tier
from insight_copilot.errors import StatisticalError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

TIER_RELIABILITY_TARGETS: tuple[tuple[Tier, float], ...] = (
    ("High", 0.90),
    ("Moderate", 0.70),
    ("Low", 0.50),
)
"""What each tier is promising: "High" means right about nine times in ten, "Moderate"
about seven, "Low" better than a coin. Ordered strongest first. These are the claims;
the boundaries that deliver them are read off the curve."""

SEARCH_RESOLUTION = 1001
"""Points on [0, 1] at which the curve is inverted. Isotonic maps are step functions,
so a grid finer than the number of steps costs nothing and misses nothing."""


class ProbabilityMap(Protocol):
    """Anything that maps a composite score to a probability — the calibrator."""

    def transform(self, score: float) -> float:
        """The calibrated probability for one composite score."""
        ...


@dataclass(frozen=True)
class TierBoundaries:
    """The score at which each tier begins, plus how it was arrived at."""

    abstain_below: float
    low_above: float
    moderate_above: float
    high_above: float
    derived: bool
    detail: str

    def tier_for(self, calibrated: float) -> Tier:
        """Band one calibrated score. The only place a tier name is assigned."""
        if calibrated < self.abstain_below:
            return "Insufficient"
        if calibrated >= self.high_above:
            return "High"
        if calibrated >= self.moderate_above:
            return "Moderate"
        if calibrated >= self.low_above:
            return "Low"
        return "Insufficient"

    @classmethod
    def from_policy(cls, policy: ConfidencePolicy) -> TierBoundaries:
        """The contract's own bands, used until a backtest supplies a curve.

        ``High`` is placed at the midpoint between the hedge boundary and certainty
        rather than at a hand-picked 0.9: with no curve there is nothing to derive it
        from, and the midpoint at least follows from the two numbers the contract does
        state instead of inventing a third.
        """
        high = 0.5 * (policy.hedge_below + 1.0)
        return cls(
            abstain_below=policy.abstain_below,
            low_above=policy.abstain_below,
            moderate_above=policy.hedge_below,
            high_above=high,
            derived=False,
            detail="contract bands; no fitted reliability curve yet",
        )


def derive_boundaries(curve: ProbabilityMap, policy: ConfidencePolicy) -> TierBoundaries:
    """Invert a fitted reliability curve into tier boundaries.

    For each tier's promised hit rate, find the lowest composite score whose calibrated
    probability meets it. Monotonicity of the isotonic map is what makes "the lowest
    such score" well defined; a non-monotone calibrator would have no such inverse,
    which is one of the reasons the calibrator is isotonic.

    A tier whose promise the curve never reaches is pushed up to the next boundary,
    collapsing it: if nothing in the backtest ever earned 90%, the system should not
    have a "High" band that nothing can enter, and it certainly should not lower the
    promise so the band fills up.
    """
    grid = np.linspace(0.0, 1.0, SEARCH_RESOLUTION)
    calibrated = np.array([curve.transform(float(point)) for point in grid])
    if not np.all(np.diff(calibrated) >= -1e-9):
        raise StatisticalError("the reliability curve is not monotone; cannot invert it")

    thresholds: dict[Tier, float] = {}
    ceiling = 1.0
    for tier, target in TIER_RELIABILITY_TARGETS:
        reached = grid[calibrated >= target]
        # Never below a stronger tier's boundary: a weaker promise met at a higher
        # score than a stronger one would mean the bands overlap.
        thresholds[tier] = float(min(reached[0], ceiling)) if reached.size else ceiling
        ceiling = thresholds[tier]

    abstain = max(policy.abstain_below, thresholds["Low"])
    unreached = [tier for tier, target in TIER_RELIABILITY_TARGETS if thresholds[tier] >= 1.0]
    detail = (
        "derived from the fitted curve at targets "
        + ", ".join(f"{tier} {target:.0%}" for tier, target in TIER_RELIABILITY_TARGETS)
        + (f"; unreachable in this backtest: {', '.join(unreached)}" if unreached else "")
    )
    boundaries = TierBoundaries(
        abstain_below=abstain,
        low_above=abstain,
        moderate_above=max(thresholds["Moderate"], abstain),
        high_above=max(thresholds["High"], abstain),
        derived=True,
        detail=detail,
    )
    logger.info(
        "tiers.derived",
        abstain_below=boundaries.abstain_below,
        moderate_above=boundaries.moderate_above,
        high_above=boundaries.high_above,
    )
    return boundaries
