"""Call site ① — the query planner. **Structured facts in, a typed plan out.**

The planner receives no documents and no confidential values: it sees a KPI id, a
period, a movement and the dimension names the contract already publishes. It returns a
search plan, and that plan is validated against a domain allowlist built from the
contract itself. A plan naming a dimension the contract does not declare is rejected
before anything is executed — which is why a prompt-injected "also return margin by
customer" cannot become a query.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Literal

from pydantic import Field, ValidationError

from insight_copilot.contracts.common import StrictModel
from insight_copilot.contracts.models import KPIContract
from insight_copilot.errors import LLMError
from insight_copilot.llm.router import ModelRouter
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

Intent = Literal["explain_movement", "compare_periods", "rank_segments", "check_health"]

SYSTEM = """You plan an analytical investigation. You never compute or state a number.
Return only JSON with keys: intent, kpi_id, dimensions, drivers, document_kinds,
rationale. Every dimension and driver must come from the allowlist you are given."""

DOCUMENT_KINDS = frozenset(
    {
        "ops_incident",
        "pricing_memo",
        "campaign_brief",
        "supplier_email",
        "news_article",
        "weekly_review",
    }
)


class SearchPlan(StrictModel):
    """A validated investigation plan. Nothing here can widen a query."""

    intent: Intent
    kpi_id: str
    dimensions: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    document_kinds: list[str] = Field(default_factory=list)
    rationale: str = ""


class QueryPlanner:
    """Turns a movement into a plan, and refuses any plan outside the contract."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    def plan(
        self,
        contract: KPIContract,
        *,
        period: tuple[dt.date, dt.date],
        delta_pct: float,
        watermark: str | None = None,
    ) -> SearchPlan:
        """Ask for a plan, then validate every token in it against the contract."""
        allowlist = self._allowlist(contract)
        user = json.dumps(
            {
                "kpi_id": contract.kpi.id,
                "period": [period[0].isoformat(), period[1].isoformat()],
                "movement_pct": round(delta_pct, 2),
                "allowed_dimensions": sorted(allowlist["dimensions"]),
                "allowed_drivers": sorted(allowlist["drivers"]),
                "allowed_document_kinds": sorted(DOCUMENT_KINDS),
            },
            sort_keys=True,
        )
        response = self._router.complete(
            call_site="planner",
            system=SYSTEM,
            user=user,
            cache_key=self._router.semantic_key(
                intent=f"plan:{contract.kpi.id}:{period[0]}:{period[1]}",
                watermark=watermark,
                contract_version=contract.contract_version,
            ),
        )
        return self.validate(response.text, contract)

    @staticmethod
    def _allowlist(contract: KPIContract) -> dict[str, set[str]]:
        """The only tokens a plan may contain, taken from the contract."""
        return {
            "dimensions": set(contract.definition.dimensions),
            "drivers": {driver.id for driver in contract.drivers.exogenous},
        }

    def validate(self, text: str, contract: KPIContract) -> SearchPlan:
        """Parse and check. **A value outside the allowlist rejects the whole plan.**"""
        try:
            payload = json.loads(_strip_fences(text))
            plan = SearchPlan.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError("planner returned an unusable plan", detail=str(exc)) from exc

        allowlist = self._allowlist(contract)
        problems: list[str] = []
        if plan.kpi_id != contract.kpi.id:
            problems.append(f"plan names KPI {plan.kpi_id!r}, not {contract.kpi.id!r}")
        problems.extend(
            f"dimension {name!r} is not declared by the contract"
            for name in plan.dimensions
            if name not in allowlist["dimensions"]
        )
        problems.extend(
            f"driver {name!r} is not declared by the contract"
            for name in plan.drivers
            if name not in allowlist["drivers"]
        )
        problems.extend(
            f"document kind {name!r} does not exist"
            for name in plan.document_kinds
            if name not in DOCUMENT_KINDS
        )
        if problems:
            logger.warning("planner.rejected", kpi=contract.kpi.id, problems=problems)
            raise LLMError(
                "planner produced a plan outside the contract's allowlist",
                detail="; ".join(problems),
            )
        return plan


def _strip_fences(text: str) -> str:
    """Models like to wrap JSON in markdown fences. Strip them before parsing."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()
