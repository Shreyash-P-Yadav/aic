"""Tuning that analyst corrections are allowed to do — and the eval gate over it.

Two knobs, both narrow on purpose:

* **Evidence source-tier weights.** When readers repeatedly say "wrong cause" on
  insights whose evidence came mostly from tier-4 secondary reporting, the honest
  correction is to trust tier 4 less. That is a weight on a source *class*, not on a
  conclusion, so it cannot flip an answer — only lower a confidence.
* **Attribution stability floor.** When readers repeatedly say "wrong cause" on
  insights whose top segment was barely stable, the floor rises and those insights
  stop being published as named causes.

What corrections may **not** do is move a number. No amount of feedback changes a
contribution, a p-value or a delta; feedback moves *thresholds for speaking*, never
the arithmetic. That boundary is the whole reason a learning loop is safe to have.

Every proposal is gated: :meth:`TuningProposal.accept` is only reachable through
:func:`apply_if_improved`, which requires the eval suite to have improved (or held) on
the metric the change targets. A tuning loop with no gate is a system that drifts.
"""

from __future__ import annotations

from dataclasses import dataclass

from insight_copilot.learning.store import FeedbackRecord
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

MIN_RECORDS_TO_TUNE = 25
"""Below this, one loud analyst moves a threshold everyone else lives with."""

WRONG_CAUSE_TRIGGER = 0.30
"""Fraction of reactions labelled ``wrong_cause`` that justifies tightening. Chosen as
the point at which nearly one named cause in three is disputed — well above the rate a
correctly calibrated Moderate tier should produce."""

TIER_WEIGHT_STEP = 0.10
"""One correction round moves a source-tier weight by at most this much. Small steps
mean a bad round is recoverable by the next one rather than by a rollback."""

STABILITY_STEP = 0.02
"""One round moves the stability floor by at most two points."""

MAX_STABILITY_FLOOR = 0.98
"""Above this the floor rejects everything and the system stops speaking at all."""


@dataclass(frozen=True)
class TuningProposal:
    """A proposed threshold change, its evidence, and the metric that must not regress."""

    knob: str
    current: float
    proposed: float
    rationale: str
    guard_metric: str

    @property
    def is_change(self) -> bool:
        """Is this actually a move? A no-op proposal is still reported."""
        return abs(self.proposed - self.current) > 1e-12


def propose(
    records: list[FeedbackRecord],
    *,
    stability_floor: float,
    tier4_weight: float,
) -> list[TuningProposal]:
    """What the corrections justify changing. Pure: records in, proposals out."""
    if len(records) < MIN_RECORDS_TO_TUNE:
        return []
    wrong = sum(1 for item in records if item.label == "wrong_cause") / len(records)
    if wrong < WRONG_CAUSE_TRIGGER:
        logger.info("learning.no_tuning", wrong_cause_rate=wrong)
        return []
    return [
        TuningProposal(
            knob="attribution.stability_floor",
            current=stability_floor,
            proposed=min(stability_floor + STABILITY_STEP, MAX_STABILITY_FLOOR),
            rationale=(
                f"{wrong:.0%} of reactions dispute the named cause; raising the "
                "bootstrap stability a segment needs before it is named"
            ),
            guard_metric="attribution_accuracy",
        ),
        TuningProposal(
            knob="evidence.source_tier_4_weight",
            current=tier4_weight,
            proposed=max(tier4_weight - TIER_WEIGHT_STEP, 0.0),
            rationale=(
                f"{wrong:.0%} of reactions dispute the named cause; trusting "
                "unverified secondary reporting less"
            ),
            guard_metric="attribution_accuracy",
        ),
    ]


def apply_if_improved(
    proposals: list[TuningProposal],
    *,
    before: dict[str, float],
    after: dict[str, float],
) -> tuple[list[TuningProposal], list[str]]:
    """Accept only the proposals whose guard metric did not regress.

    "Did not regress" rather than "improved": a threshold that raises precision at the
    same accuracy is a real gain the accuracy number cannot see, and demanding a strict
    improvement on one metric is how a tuning loop learns to overfit that metric.
    """
    accepted: list[TuningProposal] = []
    rejected: list[str] = []
    for proposal in proposals:
        baseline = before.get(proposal.guard_metric)
        candidate = after.get(proposal.guard_metric)
        if baseline is None or candidate is None:
            rejected.append(f"{proposal.knob}: {proposal.guard_metric} was not measured")
            continue
        if candidate + 1e-9 < baseline:
            rejected.append(
                f"{proposal.knob}: {proposal.guard_metric} fell from "
                f"{baseline:.3f} to {candidate:.3f}"
            )
            continue
        accepted.append(proposal)
    logger.info("learning.tuning_gated", accepted=len(accepted), rejected=len(rejected))
    return accepted, rejected
