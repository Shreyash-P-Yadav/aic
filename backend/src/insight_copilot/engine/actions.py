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
        today: dt.date,
    ) -> list[RecommendedAction]:
        """Every admissible action for this driver, or none at Low/Insufficient."""
        if confidence.tier in SUPPRESSED_TIERS:
            logger.info(
                "actions.suppressed", tier=confidence.tier, kpi=contract.kpi.id, driver=driver_id
            )
            return []
        chosen: list[RecommendedAction] = []
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
                continue
            chosen.append(
                RecommendedAction(
                    spec=spec,
                    driver_id=driver_id,
                    expected_impact=propagate_impact(
                        baseline_value=baseline_value,
                        elasticity=elasticity,
                        elasticity_interval=elasticity_interval,
                        lever_change=lever_change,
                        effect_fraction=spec.effect_fraction,
                    ),
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
        logger.info("actions.selected", kpi=contract.kpi.id, driver=driver_id, n=len(chosen))
        return chosen


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
