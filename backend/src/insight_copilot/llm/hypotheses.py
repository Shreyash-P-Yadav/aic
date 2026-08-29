"""Call site ② — the hypothesis proposer. **Cite or drop.**

The model's job here is to *propose* candidate explanations, which is a genuinely
useful thing a model is good at and a statistical engine is not: it can read an ops
ticket and a pricing memo and suggest that they are related. What it must never do is
decide whether the suggestion is true, or attach a number to it.

So every proposed hypothesis must cite a document that is actually in the evidence
bundle. A claim citing nothing, or citing a document id that does not exist, is dropped
**before scoring** — not down-weighted, dropped. Down-weighting an uncited claim leaves
it in the ranking where a tie can promote it; dropping it means an invented citation
can never influence an output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import Field, ValidationError

from insight_copilot.contracts.common import StrictModel
from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.bundle import InsightEvidenceBundle
from insight_copilot.errors import LLMError
from insight_copilot.llm.planner import _strip_fences
from insight_copilot.llm.router import ModelRouter
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

SYSTEM = """You propose candidate explanations for a measured movement. You never state
or alter a number, and you never decide which explanation is correct. Every hypothesis
must cite at least one document id from the list you are given. Return only JSON:
{"hypotheses": [{"driver_id": ..., "claim": ..., "cites": [...]}]}"""


class Hypothesis(StrictModel):
    """One proposed explanation, with the documents it rests on."""

    driver_id: str
    claim: str
    cites: list[str] = Field(default_factory=list)


class HypothesisSet(StrictModel):
    """What the model proposed, before the cite-or-drop filter."""

    hypotheses: list[Hypothesis] = Field(default_factory=list)


@dataclass(frozen=True)
class ProposalResult:
    """What survived, what was dropped, and why."""

    kept: list[Hypothesis]
    dropped_uncited: list[Hypothesis]
    dropped_unknown_driver: list[Hypothesis]

    @property
    def detail(self) -> str:
        """A line for the evidence drawer."""
        return (
            f"{len(self.kept)} hypothesis(es) kept; "
            f"{len(self.dropped_uncited)} dropped for citing nothing in the bundle; "
            f"{len(self.dropped_unknown_driver)} dropped for naming an undeclared driver"
        )


class HypothesisProposer:
    """Proposes candidate causes, then drops every one that cannot cite the bundle."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    def propose(self, bundle: InsightEvidenceBundle, contract: KPIContract) -> ProposalResult:
        """Ask for candidates, then apply cite-or-drop against this bundle."""
        documents = [item.doc_id for item in bundle.evidence]
        user = json.dumps(
            {
                "kpi_id": bundle.kpi_id,
                "movement_pct": round(bundle.delta_pct, 2),
                "top_segments": [item.label for item in bundle.segments[:4]],
                "allowed_drivers": sorted(driver.id for driver in contract.drivers.exogenous),
                "available_documents": [
                    {"doc_id": item.doc_id, "title": item.title, "kind": item.kind}
                    for item in bundle.evidence
                ],
            },
            sort_keys=True,
        )
        response = self._router.complete(
            call_site="hypotheses",
            system=SYSTEM,
            user=user,
            cache_key=self._router.semantic_key(
                intent=f"hypotheses:{bundle.insight_id}",
                watermark=bundle.watermark,
                contract_version=contract.contract_version,
            ),
        )
        return self.filter(response.text, documents, contract)

    @staticmethod
    def filter(text: str, document_ids: list[str], contract: KPIContract) -> ProposalResult:
        """Parse, then drop anything uncited or naming a driver the contract lacks."""
        try:
            proposed = HypothesisSet.model_validate(json.loads(_strip_fences(text)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError("hypothesis proposer returned unusable output", detail=str(exc)) from exc

        known_documents = set(document_ids)
        known_drivers = {driver.id for driver in contract.drivers.exogenous}
        kept: list[Hypothesis] = []
        uncited: list[Hypothesis] = []
        unknown: list[Hypothesis] = []
        for item in proposed.hypotheses:
            if item.driver_id not in known_drivers:
                unknown.append(item)
                continue
            supported = [doc for doc in item.cites if doc in known_documents]
            if not supported:
                uncited.append(item)
                continue
            kept.append(Hypothesis(driver_id=item.driver_id, claim=item.claim, cites=supported))
        logger.info(
            "hypotheses.filtered",
            kept=len(kept),
            dropped_uncited=len(uncited),
            dropped_unknown_driver=len(unknown),
        )
        return ProposalResult(kept=kept, dropped_uncited=uncited, dropped_unknown_driver=unknown)
