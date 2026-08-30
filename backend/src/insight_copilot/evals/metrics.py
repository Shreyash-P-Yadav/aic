"""Pure metric functions. Arrays in, numbers out — no I/O, no globals, no state.

Every target in the eval report is computed here so that the target and the number
that is compared against it come from the same, separately testable, place. A metric
that is computed inline inside a reporting loop is a metric nobody can unit-test, and
an untestable metric is how a system reports a score it did not earn.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from insight_copilot.errors import StatisticalError

DEFAULT_RELIABILITY_BINS = 10
"""Ten equal-width bins is the convention in the calibration literature and keeps the
per-bin count interpretable at the corpus sizes this system backtests on."""


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of the reliability curve, always carrying its own ``n``.

    A calibration plot without per-bin counts is decorative: a bin holding two points
    looks exactly like a bin holding two hundred and says nothing about either.
    """

    lower: float
    upper: float
    n: int
    mean_score: float
    hit_rate: float

    @property
    def gap(self) -> float:
        """|predicted - observed| in this bin — the term ECE averages."""
        return abs(self.mean_score - self.hit_rate)


def reliability_curve(
    scores: np.ndarray, outcomes: np.ndarray, *, bins: int = DEFAULT_RELIABILITY_BINS
) -> list[ReliabilityBin]:
    """Bin ``(score, outcome)`` pairs into equal-width bins over [0, 1]."""
    scores, outcomes = _paired(scores, outcomes)
    edges = np.linspace(0.0, 1.0, bins + 1)
    # ``right=True`` on the last bin only, so a score of exactly 1.0 lands in the top
    # bin rather than in a bin of its own that would hold a single point.
    index = np.clip(np.digitize(scores, edges[1:-1], right=False), 0, bins - 1)
    curve: list[ReliabilityBin] = []
    for position in range(bins):
        members = index == position
        count = int(members.sum())
        curve.append(
            ReliabilityBin(
                lower=float(edges[position]),
                upper=float(edges[position + 1]),
                n=count,
                mean_score=float(scores[members].mean()) if count else float("nan"),
                hit_rate=float(outcomes[members].mean()) if count else float("nan"),
            )
        )
    return curve


def expected_calibration_error(
    scores: np.ndarray, outcomes: np.ndarray, *, bins: int = DEFAULT_RELIABILITY_BINS
) -> float:
    """ECE: the count-weighted mean gap between predicted and observed hit rate.

    Empty bins contribute nothing rather than contributing a zero gap: a bin nobody
    landed in is not evidence of good calibration.
    """
    curve = reliability_curve(scores, outcomes, bins=bins)
    total = sum(item.n for item in curve)
    if total == 0:
        raise StatisticalError("no points to compute ECE over")
    return float(sum(item.n * item.gap for item in curve if item.n) / total)


def brier_score(scores: np.ndarray, outcomes: np.ndarray) -> float:
    """Mean squared error of the probability forecast. Reported beside ECE because
    ECE alone can be gamed by a constant predictor at the base rate."""
    scores, outcomes = _paired(scores, outcomes)
    return float(np.mean((scores - outcomes) ** 2))


@dataclass(frozen=True)
class DetectionCounts:
    """Confusion counts for day-level detection against the truth ledger."""

    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        """Of the days flagged, how many fell inside a real event window?"""
        flagged = self.true_positive + self.false_positive
        return self.true_positive / flagged if flagged else float("nan")

    @property
    def recall(self) -> float:
        """Of the real events, how many were flagged on at least one day?"""
        real = self.true_positive + self.false_negative
        return self.true_positive / real if real else float("nan")

    @property
    def f1(self) -> float:
        """Harmonic mean; ``nan`` when either side is undefined."""
        p, r = self.precision, self.recall
        return 2.0 * p * r / (p + r) if p + r > 0 else float("nan")


def mean_relative_error(estimated: np.ndarray, truth: np.ndarray, *, floor: float = 1e-9) -> float:
    """Mean of ``|est - true| / max(|true|, floor)``.

    Relative rather than absolute because the ledger's contributions span four orders
    of magnitude, and an absolute error would be a report on the largest event only.
    """
    estimated, truth = _paired(estimated, truth)
    scale = np.maximum(np.abs(truth), floor)
    return float(np.mean(np.abs(estimated - truth) / scale))


def kendall_tau(estimated_rank: list[str], true_rank: list[str]) -> float:
    """Kendall's tau-b between two orderings of the same items.

    Ranking is the claim a driver attribution actually makes to a decision-maker:
    "this mattered most". Tau measures that claim directly, where a correlation on the
    coefficients would reward getting the magnitudes right while ordering them wrongly.
    """
    shared = [item for item in estimated_rank if item in true_rank]
    if len(shared) < 2:
        raise StatisticalError(
            "tau needs at least two shared items",
            detail=f"{len(shared)} shared between {estimated_rank} and {true_rank}",
        )
    estimated_positions = [shared.index(item) for item in shared]
    true_positions = [true_rank.index(item) for item in shared]
    tau = stats.kendalltau(estimated_positions, true_positions).statistic
    return float(tau)


def _paired(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two finite float arrays of equal length, or a typed error."""
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape:
        raise StatisticalError("metric inputs disagree in length", detail=f"{a.shape} vs {b.shape}")
    usable = np.isfinite(a) & np.isfinite(b)
    if not usable.any():
        raise StatisticalError("no finite pairs to measure")
    return a[usable], b[usable]
