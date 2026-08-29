"""Materiality and priority: which detections deserve the expensive path.

Two independent hurdles, and a detection must clear **both**:

* **Statistical.** It survived the conformal test and the false-discovery correction.
* **Business.** It clears the contract's own floor — an absolute rupee impact *and* a
  percentage move. A statistically flawless 0.4% wobble on a tier-1 KPI is real and
  not worth a CFO's attention, and a system that cannot say so is a system nobody
  keeps switched on.

Priority is a rule score multiplied by a learned ranker. The ranker is **disabled below
a minimum label count and reverts to rules if it goes stale**, because a ranker trained
on nine feedback events is a random number with a model's authority.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.detect import Detection
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

TIER_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.35}
"""Tier-1 is the headline set. The weights are a business ordering, not an estimate,
which is why they are a named constant and not a fitted parameter."""

PERSISTENCE_CAP_DAYS = 7.0
"""A move that has persisted a week is fully persistent for ranking purposes. Beyond
that it is a level shift, and a level shift is not more urgent for being older."""

MIN_RANKER_LABELS = 40
"""Below forty labelled outcomes the ranker is switched off. Chosen so each of the
four feedback classes has ten examples before the model is allowed an opinion."""

RANKER_STALENESS_DAYS = 45
"""A ranker not refitted within this window reverts to rules. Its features are
seasonal; a model fitted before the festival period is describing a different world."""


class PriorityRanker(Protocol):
    """The learned half of the priority score. Supplied by P11's learning loop."""

    @property
    def label_count(self) -> int:
        """How many labelled outcomes the current fit was trained on."""

    @property
    def fitted_at(self) -> dt.date | None:
        """When it was last refitted, or ``None`` if never."""

    def score(self, features: dict[str, float]) -> float:
        """A multiplier in roughly ``[0.5, 1.5]``."""


@dataclass(frozen=True)
class GateVerdict:
    """One detection, judged."""

    detection: Detection
    passed_statistical: bool
    passed_business: bool
    impact: float
    priority: float
    ranker_used: bool
    reason: str

    @property
    def material(self) -> bool:
        """Did it clear both hurdles? Only then does the expensive path run."""
        return self.passed_statistical and self.passed_business


class MaterialityGate:
    """Applies a KPI contract's materiality thresholds and ranks what survives."""

    def __init__(self, ranker: PriorityRanker | None = None) -> None:
        self._ranker = ranker

    def judge(
        self,
        detection: Detection,
        contract: KPIContract,
        *,
        today: dt.date,
        persistence_days: int = 1,
    ) -> GateVerdict:
        """Score one detection against its contract."""
        business = contract.materiality.business
        impact = abs(detection.delta)
        pct = abs(detection.delta_pct)
        floor_inr = business.min_abs_impact_inr or 0.0
        floor_pct = business.min_pct_move or 0.0

        clears_absolute = impact >= floor_inr
        clears_relative = pct >= floor_pct
        passed_business = clears_absolute and clears_relative
        passed_statistical = detection.passed_fdr

        rule_score = self._rule_score(contract, impact, persistence_days)
        multiplier, used = self._ranker_multiplier(detection, contract, today)
        return GateVerdict(
            detection=detection,
            passed_statistical=passed_statistical,
            passed_business=passed_business,
            impact=impact,
            priority=rule_score * multiplier,
            ranker_used=used,
            reason=self._reason(
                passed_statistical, clears_absolute, clears_relative, impact, pct, contract
            ),
        )

    def rank(self, verdicts: list[GateVerdict]) -> list[GateVerdict]:
        """Material verdicts, most urgent first."""
        return sorted(
            (item for item in verdicts if item.material),
            key=lambda item: item.priority,
            reverse=True,
        )

    # ---------------------------------------------------------------- scoring --
    @staticmethod
    def _rule_score(contract: KPIContract, impact: float, persistence_days: int) -> float:
        """``|impact| x tier_weight x persistence_factor``, the contract's own formula."""
        tier = TIER_WEIGHT.get(contract.kpi.tier, TIER_WEIGHT[3])
        persistence = min(persistence_days, PERSISTENCE_CAP_DAYS) / PERSISTENCE_CAP_DAYS
        return float(impact * tier * (0.5 + 0.5 * persistence))

    def _ranker_multiplier(
        self, detection: Detection, contract: KPIContract, today: dt.date
    ) -> tuple[float, bool]:
        """Ask the ranker, unless it is untrained or stale. Both refusals are logged."""
        if self._ranker is None:
            return 1.0, False
        if self._ranker.label_count < MIN_RANKER_LABELS:
            logger.info("gate.ranker_disabled", reason="labels", labels=self._ranker.label_count)
            return 1.0, False
        fitted = self._ranker.fitted_at
        if fitted is None or (today - fitted).days > RANKER_STALENESS_DAYS:
            logger.info("gate.ranker_disabled", reason="stale", fitted_at=str(fitted))
            return 1.0, False
        features = {
            "abs_delta_pct": abs(detection.delta_pct),
            "neg_log_p": float(-np.log(max(detection.p_value, 1e-12))),
            "tier": float(contract.kpi.tier),
        }
        return float(self._ranker.score(features)), True

    @staticmethod
    def _reason(
        statistical: bool,
        absolute: bool,
        relative: bool,
        impact: float,
        pct: float,
        contract: KPIContract,
    ) -> str:
        """Why this detection was or was not promoted, in the contract's own numbers."""
        business = contract.materiality.business
        if not statistical:
            return "did not survive the false-discovery correction across the scan"
        if not absolute:
            return (
                f"impact {impact:,.0f} is below the contract's floor of "
                f"{business.min_abs_impact_inr or 0:,.0f}"
            )
        if not relative:
            return (
                f"{pct:.2f}% move is below the contract's {business.min_pct_move or 0:.2f}% floor"
            )
        return (
            f"material: {pct:.2f}% and {impact:,.0f} both clear the contract's floors "
            f"({business.min_pct_move or 0:.2f}%, {business.min_abs_impact_inr or 0:,.0f})"
        )
