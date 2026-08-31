"""The report's two tables, plus the two small helpers both sections need.

Kept apart from the sections because a table is a different kind of output: a section
answers "did this meet its target", a table shows the reader the distribution behind
that answer so they can disagree with it.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from insight_copilot.engine.calibration import IsotonicCalibrator
from insight_copilot.engine.tiers import TierBoundaries
from insight_copilot.evals.backtest import BacktestOutcome
from insight_copilot.evals.metrics import reliability_curve
from insight_copilot.evals.models import ReliabilityRow, TierRow


# --------------------------------------------------------------------- tables --
def reliability_rows(
    holdout: list[BacktestOutcome], calibrator: IsotonicCalibrator
) -> list[ReliabilityRow]:
    """The reliability curve as report rows, empty bins included with ``n = 0``."""
    rows = [item for item in holdout if item.gradeable]
    if not rows:
        return []
    calibrated = np.array([calibrator.transform(item.raw_score) for item in rows])
    truth = np.array([float(item.correct) for item in rows])
    return [
        ReliabilityRow(
            lower=item.lower,
            upper=item.upper,
            n=item.n,
            mean_score=item.mean_score if item.n else 0.0,
            hit_rate=item.hit_rate if item.n else 0.0,
        )
        for item in reliability_curve(calibrated, truth)
    ]


def tier_rows(
    holdout: list[BacktestOutcome],
    calibrator: IsotonicCalibrator,
    boundaries: TierBoundaries,
) -> list[TierRow]:
    """Observed hit rate per tier, with ``n`` — the table the spec asks for by name."""
    rows = [item for item in holdout if item.gradeable]
    banded: dict[str, list[tuple[float, bool]]] = {}
    for item in rows:
        calibrated = calibrator.transform(item.raw_score)
        banded.setdefault(boundaries.tier_for(calibrated), []).append((calibrated, item.correct))
    order = {
        "High": boundaries.high_above,
        "Moderate": boundaries.moderate_above,
        "Low": boundaries.low_above,
        "Insufficient": 0.0,
    }
    return [
        TierRow(
            tier=tier,
            n=len(banded.get(tier, [])),
            hit_rate=float(np.mean([hit for _, hit in banded[tier]])) if banded.get(tier) else 0.0,
            mean_score=float(np.mean([score for score, _ in banded[tier]]))
            if banded.get(tier)
            else 0.0,
            boundary=boundary,
        )
        for tier, boundary in order.items()
    ]


def discrimination(scores: np.ndarray, truth: np.ndarray) -> float:
    """Rank-based AUC: the probability a correct call scores above an incorrect one.

    Computed from ranks rather than by sweeping thresholds, which handles ties (an
    isotonic map produces many) the way the definition intends: a tie counts a half.
    """
    positives, negatives = scores[truth > 0.5], scores[truth <= 0.5]
    if positives.size == 0 or negatives.size == 0:
        return float("nan")
    from scipy.stats import rankdata

    ranks = rankdata(scores)
    positive_rank_sum = float(ranks[truth > 0.5].sum())
    n_pos, n_neg = float(positives.size), float(negatives.size)
    return (positive_rank_sum - n_pos * (n_pos + 1.0) / 2.0) / (n_pos * n_neg)


def days_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every day in an inclusive window."""
    return [start + dt.timedelta(days=offset) for offset in range((end - start).days + 1)]
