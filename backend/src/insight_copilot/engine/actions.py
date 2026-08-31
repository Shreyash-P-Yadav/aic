"""Actions: driver -> controllable lever -> action -> expected impact -> owner ->
confidence -> monitoring plan.

That chain is the output structure, exactly, and every link is governed rather than
generated:

* the **driver** comes from rung 3 of the ladder;
* the **lever** and the **action** come from a YAML catalog a human owns, so no model
  ever invents an intervention;
* the **expected impact** is computed from the estimated elasticity **with its
  confidence interval propagated** — never a point estimate, because an action proposed
  on a point estimate hides the very uncertainty that should decide whether to take it;
* the **owner** and the **approval threshold** come from the catalog's decision rights;
* the **confidence** is the tier the confidence layer computed;
* the **monitoring plan** names the KPI, the checkpoints and the success threshold, so
  the recommendation can be scored later rather than admired now.

**Actions are suppressed entirely at Low or Insufficient confidence.** A recommendation
the system is not confident in is worse than silence: it spends the trust that the
abstention path exists to protect.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from insight_copilot.contracts.common import StrictModel
from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.confidence import ConfidenceResult, Tier
from insight_copilot.errors import ContractError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

CATALOG_DIR = Path(__file__).resolve().parents[1] / "contracts" / "catalogs"

SUPPRESSED_TIERS: frozenset[Tier] = frozenset({"Low", "Insufficient"})
"""Below Moderate, no action is proposed. The tier constrains what may be *said*, and
a recommendation is the strongest thing the system can say."""

Comparison = Literal["above", "below"]


class Precondition(StrictModel):
    """A condition on live data that must hold before an action is proposed."""

    metric: str
    comparison: Comparison
    value: float
    scope: str

    def holds(self, observed: dict[str, float]) -> bool | None:
        """True, False, or ``None`` when the metric was not supplied.

        ``None`` matters: an unchecked precondition is not a satisfied one, and an
        action whose preconditions could not be evaluated is withheld rather than
        proposed with a shrug.
        """
        if self.metric not in observed:
            return None
        value = observed[self.metric]
        return value > self.value if self.comparison == "above" else value < self.value

    @property
    def detail(self) -> str:
        """The condition in words, for the card."""
        return f"{self.metric} {self.comparison} {self.value:g} ({self.scope})"


class MonitoringPlan(StrictModel):
    """How the recommendation will be scored after it is taken."""

    kpi: str
    checkpoint_days: list[int]
    success_threshold_pct: float


class ActionSpec(StrictModel):
    """One governed intervention. Authored by a human, never by a model."""

    id: str
    driver: str
    lever: str
    title: str
    description: str
    preconditions: list[Precondition] = Field(default_factory=list)
    elasticity_driver: str
    effect_fraction: float = Field(gt=0, le=1)
    owner_role: str
    approval_threshold_inr: float = Field(ge=0)
    monitoring: MonitoringPlan
    lead_time_days: int = Field(ge=0)


class ActionCatalog(StrictModel):
    """A domain's actions, loaded from the file a KPI contract's ``actions_ref`` names."""

    catalog_id: str
    domain: str
    actions: list[ActionSpec]

    @classmethod
    def load(cls, reference: str, *, root: Path | None = None) -> ActionCatalog:
        """Resolve a contract's ``actions_ref`` to a catalog on disk."""
        path = (root or CATALOG_DIR.parent) / reference
        try:
            payload = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise ContractError(f"unreadable action catalog {reference}", detail=str(exc)) from exc
        return cls.model_validate(payload)

    def for_driver(self, driver_id: str) -> list[ActionSpec]:
        """Actions whose declared driver is the one the ladder found."""
        return [action for action in self.actions if action.driver == driver_id]


@dataclass(frozen=True)
class ImpactInterval:
    """An expected impact with its interval. **Never a point estimate downstream.**"""

    central: float
    low: float
    high: float

    @property
    def detail(self) -> str:
        """The interval as a sentence, in the KPI's own units."""
        return f"{self.central:,.0f} (95% interval {self.low:,.0f} to {self.high:,.0f})"


@dataclass(frozen=True)
class RecommendedAction:
    """One action, priced, owned and monitored."""

    spec: ActionSpec
    driver_id: str
    expected_impact: ImpactInterval
    owner_role: str
    needs_approval: bool
    confidence_tier: Tier
    preconditions_met: list[str]
    preconditions_failed: list[str]
    preconditions_unchecked: list[str]
    earliest_effect: dt.date

    @property
    def detail(self) -> str:
        """The card's one-line summary, in the design's own output order."""
        return (
            f"{self.driver_id} -> {self.spec.lever} -> {self.spec.title}: "
            f"expected impact {self.expected_impact.detail}; owner {self.owner_role}"
            f"{' (approval required)' if self.needs_approval else ''}; "
            f"confidence {self.confidence_tier}; monitored on "
            f"{self.spec.monitoring.kpi} at days {self.spec.monitoring.checkpoint_days}"
        )


def propagate_impact(
    *,
    baseline_value: float,
    elasticity: float,
    elasticity_interval: tuple[float, float],
    lever_change: float,
    effect_fraction: float,
) -> ImpactInterval:
    """Expected impact from an elasticity, with the estimate's interval carried through.

    ``impact = baseline * elasticity * lever_change * effect_fraction``, evaluated at
    the estimate and at both ends of its confidence interval. Propagating the interval
    rather than the point is the difference between "this will recover Rs 1.2 cr" and
    "this recovers between Rs 0.4 cr and Rs 2.0 cr" — and only the second is a
    statement a decision can be made against.
    """

    def evaluate(value: float) -> float:
        return baseline_value * value * lever_change * effect_fraction

    ends = sorted((evaluate(elasticity_interval[0]), evaluate(elasticity_interval[1])))
    return ImpactInterval(central=evaluate(elasticity), low=ends[0], high=ends[1])


@dataclass(frozen=True)
class ActionSelection:
    """What the selector proposed, and what it refused to propose and why.

    The refusals are carried rather than only logged because an empty action list is
    ambiguous on screen: "nothing to do" and "three things were considered and every one
    was ruled out" look identical, and only the second is a decision. A reader who
    cannot tell them apart has to guess whether the system thought about it.
    """

    chosen: list[RecommendedAction]
    withheld: list[str]


def _withheld_reason(title: str, failed: list[str], unchecked: list[str]) -> str:
    """Why one action was not proposed, distinguishing failed from unevaluable.

    The distinction is the whole point. A failed precondition is an answer: the data was
    consulted and it said no. An unevaluable one is the absence of an answer, and it is
    treated the same way on purpose — but a reader deserves to know which happened,
    because only one of them is fixed by building a mart.
    """
    parts: list[str] = []
    if failed:
        parts.append(f"failed {', '.join(failed)}")
    if unchecked:
        parts.append(f"could not check {', '.join(unchecked)} (no mart provides it)")
    return f"{title!r}: {'; '.join(parts)}"


class ActionSelector:
    """Chooses which governed actions to propose, and prices them."""

    def __init__(self, catalog: ActionCatalog) -> None:
        self._catalog = catalog

    def select(
        self,
        *,
        contract: KPIContract,
        driver_id: str,
        confidence: ConfidenceResult,
        baseline_value: float,
        elasticity: float,
        elasticity_interval: tuple[float, float],
        lever_change: float,
        observed: dict[str, float],
        gap: float,
        today: dt.date,
    ) -> ActionSelection:
        """Every admissible action for this driver, or none at Low/Insufficient.

        ``gap`` is the movement being answered — observed minus expected — and it sets
        the direction an action has to push. See :func:`_closes_the_gap`.
        """
        if confidence.tier in SUPPRESSED_TIERS:
            logger.info(
                "actions.suppressed", tier=confidence.tier, kpi=contract.kpi.id, driver=driver_id
            )
            return ActionSelection(
                chosen=[],
                withheld=[
                    f"every action is withheld at {confidence.tier} confidence: a "
                    f"recommendation is the strongest thing this system can say"
                ],
            )
        chosen: list[RecommendedAction] = []
        withheld: list[str] = []
        for spec in self._catalog.for_driver(driver_id):
            met, failed, unchecked = _evaluate(spec.preconditions, observed)
            if failed or unchecked:
                # An unevaluable precondition is not a satisfied one. Proposing an
                # action whose conditions could not be checked is how a recommendation
                # engine ends up advising something the data would have ruled out.
                logger.info(
                    "actions.withheld",
                    action=spec.id,
                    failed=failed,
                    unchecked=unchecked,
                )
                withheld.append(_withheld_reason(spec.title, failed, unchecked))
                continue
            impact = propagate_impact(
                baseline_value=baseline_value,
                elasticity=elasticity,
                elasticity_interval=elasticity_interval,
                lever_change=lever_change,
                effect_fraction=spec.effect_fraction,
            )
            if not _closes_the_gap(impact.central, gap):
                logger.info(
                    "actions.wrong_direction",
                    action=spec.id,
                    impact=impact.central,
                    gap=gap,
                    elasticity=elasticity,
                )
                withheld.append(
                    f"{spec.title!r}: priced with the estimated {driver_id} elasticity of "
                    f"{elasticity:+.2f}, it would push the KPI the wrong way — further from "
                    f"its baseline rather than back towards it"
                )
                continue
            chosen.append(
                RecommendedAction(
                    spec=spec,
                    driver_id=driver_id,
                    expected_impact=impact,
                    owner_role=spec.owner_role,
                    needs_approval=abs(baseline_value * lever_change * spec.effect_fraction)
                    >= spec.approval_threshold_inr,
                    confidence_tier=confidence.tier,
                    preconditions_met=met,
                    preconditions_failed=failed,
                    preconditions_unchecked=unchecked,
                    earliest_effect=today + dt.timedelta(days=spec.lead_time_days),
                )
            )
        chosen.sort(key=lambda item: abs(item.expected_impact.central), reverse=True)
        logger.info(
            "actions.selected",
            kpi=contract.kpi.id,
            driver=driver_id,
            n=len(chosen),
            withheld=len(withheld),
        )
        return ActionSelection(chosen=chosen, withheld=withheld)


def _evaluate(
    preconditions: list[Precondition], observed: dict[str, float]
) -> tuple[list[str], list[str], list[str]]:
    """Split preconditions into met, failed and unevaluable."""
    met: list[str] = []
    failed: list[str] = []
    unchecked: list[str] = []
    for condition in preconditions:
        verdict = condition.holds(observed)
        if verdict is None:
            unchecked.append(condition.detail)
        elif verdict:
            met.append(condition.detail)
        else:
            failed.append(condition.detail)
    return met, failed, unchecked


def _closes_the_gap(impact: float, gap: float) -> bool:
    """Would this action move the KPI back towards its baseline, or further from it?

    An action is priced with the elasticity the regression actually estimated, and that
    estimate is allowed to disagree with the intuition behind the catalog entry. On this
    build it does: `price_index` against net revenue comes out at **+0.93**, so cutting
    price by 8% is priced as a *loss* of Rs 1.18 crore rather than a recovery — inelastic
    demand, as estimated. Recommending it anyway would be the model overruling its own
    arithmetic, which is the one thing this system is built not to do.

    So the sign is the gate: an action must push the KPI in the direction that closes the
    movement being answered. A zero gap has no direction to close and admits nothing —
    there is no movement to correct.
    """
    if gap == 0.0 or impact == 0.0:
        return False
    return (impact > 0.0) == (gap < 0.0)
