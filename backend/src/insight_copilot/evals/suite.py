"""The golden eval suite: everything ``make verify-p11`` measures, in one place.

Targets are declared here as named constants next to the metric they govern, so a
target cannot be quietly relaxed in the same commit that misses it — the diff shows
both. When a metric misses, the suite records the measured number and the report says
FAIL. Nothing is dropped, re-weighted or re-targeted to produce a pass; the fifth law
is the reason this file exists at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from insight_copilot.contracts.governance import ConfidencePolicy
from insight_copilot.engine.calibration import IsotonicCalibrator
from insight_copilot.engine.tiers import TierBoundaries, derive_boundaries
from insight_copilot.errors import StatisticalError
from insight_copilot.evals.backtest import BacktestResult
from insight_copilot.evals.checks import LeakageFinding, NarrationScore
from insight_copilot.evals.elasticity import ElasticityComparison
from insight_copilot.evals.models import EvalReport
from insight_copilot.evals.sections import (
    attribution_section,
    calibration_section,
    detection_section,
    elasticity_section,
)
from insight_copilot.evals.sections_delivery import (
    budget_section,
    entitlement_section,
    narration_section,
)
from insight_copilot.evals.tables import discrimination, reliability_rows, tier_rows
from insight_copilot.evals.targets import MIN_DISCRIMINATION_AUC
from insight_copilot.learning.ranker import RankerStatus
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


def build_report(
    backtest: BacktestResult,
    *,
    calibrator: IsotonicCalibrator,
    boundaries: TierBoundaries,
    narration: NarrationScore | None = None,
    elasticity: ElasticityComparison | None = None,
    leakage: list[LeakageFinding] | None = None,
    ranker: RankerStatus | None = None,
    latency_ms: float | None = None,
    cost_usd: float | None = None,
    notes: list[str] | None = None,
) -> EvalReport:
    """Assemble every section. Pure with respect to I/O: nothing is written here."""
    holdout = backtest.holdout
    sections = [
        calibration_section(holdout, calibrator),
        attribution_section(backtest.outcomes),
        detection_section(backtest),
    ]
    if elasticity is not None:
        sections.append(elasticity_section(elasticity))
    if narration is not None:
        sections.append(narration_section(narration))
    if leakage is not None:
        sections.append(entitlement_section(leakage))
    sections.append(budget_section(latency_ms, cost_usd))
    return EvalReport(
        cut_date=backtest.cut_date,
        corpus_events=len(backtest.outcomes),
        fit_events=len(backtest.fit_set),
        holdout_events=len(holdout),
        excluded_events=sum(1 for item in backtest.outcomes if item.excluded_from_fit),
        tier_basis=boundaries.detail,
        ranker_status=ranker.reason if ranker else "",
        notes=list(notes or []),
        sections=sections,
        reliability=reliability_rows(holdout, calibrator),
        tiers=tier_rows(holdout, calibrator, boundaries),
    )


@dataclass(frozen=True)
class CalibrationFit:
    """A fitted map, the bands in force, and whether the map was adopted."""

    calibrator: IsotonicCalibrator
    boundaries: TierBoundaries
    adopted: bool
    discrimination: float
    detail: str


def fit_calibrator(backtest: BacktestResult) -> CalibrationFit:
    """Fit on the pre-cut events, measure discrimination on the holdout, then decide.

    Three outcomes, all reported and none silent:

    * **Not fittable** — too few gradeable events. The calibrator stays unfitted and
      the contract's bands hold.
    * **Fitted but not adopted** — the map exists and is measured, but its holdout
      discrimination is at chance, so deriving bands from it would be deriving bands
      from noise. The contract's bands hold and the report says why.
    * **Adopted** — the map discriminates, so the tier boundaries are inverted out of
      it, as law 3 requires.
    """
    policy = _default_policy()
    fallback = TierBoundaries.from_policy(policy)
    rows = [item for item in backtest.fit_set if item.gradeable]
    scores, outcomes = backtest.arrays(rows)
    calibrator = IsotonicCalibrator()
    try:
        calibrator.fit(scores, outcomes)
    except StatisticalError as exc:
        logger.warning("evals.calibration_skipped", error=str(exc))
        return CalibrationFit(calibrator, fallback, False, float("nan"), str(exc))

    holdout = [item for item in backtest.holdout if item.gradeable]
    held_scores, held_truth = backtest.arrays(holdout)
    calibrated = np.array([calibrator.transform(float(value)) for value in held_scores])
    auc = discrimination(calibrated, held_truth) if holdout else float("nan")
    if not np.isfinite(auc) or auc < MIN_DISCRIMINATION_AUC:
        return CalibrationFit(
            calibrator,
            fallback,
            False,
            auc,
            (
                f"fitted on {calibrator.n_points} events but NOT adopted: holdout "
                f"discrimination is {auc:.3f}, below the {MIN_DISCRIMINATION_AUC:.2f} "
                "floor, so the map is a constant at the base rate and the bands derived "
                "from it would admit nothing"
            ),
        )
    return CalibrationFit(
        calibrator,
        derive_boundaries(calibrator, policy),
        True,
        auc,
        f"adopted: fitted on {calibrator.n_points} events, holdout discrimination {auc:.3f}",
    )


def _default_policy() -> ConfidencePolicy:
    """The policy the tier derivation floors against.

    Imported lazily and built from the net_revenue contract's own numbers by the
    caller in production; the suite falls back to the same bands the contract ships
    so a report can be produced without a registry.
    """
    return ConfidencePolicy(min_history_days_full_stats=180, abstain_below=0.35, hedge_below=0.60)
