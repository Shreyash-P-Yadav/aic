"""Evidence retrieval: finding the document that explains a number, and scoring trust.

Four properties separate this from "search the corpus and paste the top hit":

* **Dual-date awareness.** A price revision announced in February and effective in
  April is one document with two dates. A query about April must match it on its
  *effective* date, or the April anomaly can never find its own cause. Indexing by
  publish date alone is the single most common way an evidence layer silently fails.
* **A timing gate.** A document dated after the effect it is offered to explain cannot
  be its cause, and neither can one outside the driver's contract-declared ``lag_days``
  profile. The world contains a post-dated decoy specifically to test this.
* **Noisy-OR corroboration across independent sources.** Two independent documents are
  worth more than one; six copies of the same press release are worth one. The
  independence guard is the ``syndication_group`` the ingestion layer deduplicates on —
  without it, syndication inflates confidence exactly where it should not.
* **A sufficiency check.** When nothing clears the evidence floor the answer is
  abstention, which is a designed output and not a failure.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from insight_copilot.contracts.models import ExogenousDriver
from insight_copilot.datagen.corpus.models import Document
from insight_copilot.errors import InsufficientEvidenceError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

RERANK_WEIGHT = 0.40
SOURCE_TIER_WEIGHT = 0.25
ENTITY_LINK_WEIGHT = 0.20
EXTRACTION_WEIGHT = 0.15
"""``EvidenceConf = w1*rerank + w2*source_tier + w3*entity_link + w4*extraction``.

Retrieval score leads because a document that does not match the question is not
evidence whatever its provenance. Source tier is next because an ops incident ticket
and a trade-press rewrite are not interchangeable facts. The weights sum to one."""

TIER_SCORE = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25}
"""Tier 1 is an authoritative internal record; tier 4 is unverified secondary
reporting. Linear in tier because the tiers are already an ordinal judgement."""

EVIDENCE_FLOOR_DEFAULT = 0.35
"""Overridden per KPI by the contract's ``confidence_policy.evidence_floor``."""

MAX_CANDIDATES = 40
"""Documents retrieved before the timing gate. Beyond this BM25 is returning noise."""

TOKEN = re.compile(r"[a-z0-9]+")

CORROBORATION_CAP = 0.98
"""Noisy-OR asymptotes at one. Capping below it keeps a stack of weak documents from
reading as certainty, which is the failure mode noisy-OR is otherwise prone to."""


def tokenise(text: str) -> list[str]:
    """Lowercase alphanumeric tokens. The same function indexes and queries."""
    return TOKEN.findall(text.lower())


@dataclass(frozen=True)
class EvidenceItem:
    """One retrieved document with its confidence decomposed."""

    document: Document
    rerank: float
    source_tier_score: float
    entity_link: float
    extraction: float
    matched_on: str

    @property
    def confidence(self) -> float:
        """The weighted evidence confidence, clamped to ``[0, 1]``.

        The clamp is not decoration. BM25's IDF term goes **negative** for a word that
        appears in more than half the corpus, so six near-identical documents can each
        score below zero — and an evidence confidence of -0.37 reaching a card is a
        number that means nothing and reads as something.
        """
        weighted = (
            RERANK_WEIGHT * self.rerank
            + SOURCE_TIER_WEIGHT * self.source_tier_score
            + ENTITY_LINK_WEIGHT * self.entity_link
            + EXTRACTION_WEIGHT * self.extraction
        )
        return float(min(1.0, max(0.0, weighted)))

    @property
    def independence_key(self) -> str:
        """What makes this document a *separate* witness. Syndicated copies share it."""
        return self.document.syndication_group or self.document.doc_id

    @property
    def detail(self) -> str:
        """A line for the evidence drawer."""
        return (
            f"{self.document.doc_id} ({self.document.kind}, tier "
            f"{self.document.source_tier}, matched on {self.matched_on} "
            f"{self.document.effective_date}): confidence {self.confidence:.2f}"
        )


@dataclass
class EvidenceBundle:
    """Everything retrieval found, and whether it is enough to say anything."""

    items: list[EvidenceItem] = field(default_factory=list)
    rejected_by_timing: list[str] = field(default_factory=list)
    corroboration: float = 0.0
    independent_sources: int = 0
    floor: float = EVIDENCE_FLOOR_DEFAULT
    detail: str = ""

    @property
    def sufficient(self) -> bool:
        """Did anything clear the floor? If not, the answer is abstention."""
        return self.corroboration >= self.floor and bool(self.items)

    def require_sufficient(self) -> None:
        """Raise the typed error callers convert into an ``AbstentionArtifact``."""
        if not self.sufficient:
            raise InsufficientEvidenceError(
                "no evidence cleared the floor",
                detail=(
                    f"corroboration {self.corroboration:.2f} against a floor of "
                    f"{self.floor:.2f}; {len(self.rejected_by_timing)} candidate(s) "
                    f"eliminated by the timing gate"
                ),
            )


def noisy_or(confidences: list[float]) -> float:
    """``1 - prod(1 - c)`` over **independent** sources.

    The independence is the whole assumption. Two ops tickets from different teams
    corroborate; six syndicated copies of one press release do not, and feeding them
    all in here is how an evidence layer manufactures certainty out of one fact.
    """
    if not confidences:
        return 0.0
    product = 1.0
    for value in confidences:
        product *= 1.0 - max(0.0, min(1.0, value))
    return min(CORROBORATION_CAP, 1.0 - product)


def within_lag_profile(
    document: Document, effect_day: dt.date, driver: ExogenousDriver | None
) -> bool:
    """Could this document's event have caused an effect on ``effect_day``?

    Two conditions, and both come from the contract rather than from a heuristic:
    the effective date must not post-date the effect, and the gap must fall inside the
    driver's declared ``lag_days`` window. A competitor action taken on the 16th cannot
    explain a dip that began on the 6th, however well it scores on relevance.
    """
    gap = (effect_day - document.effective_date).days
    if driver is None:
        return gap >= 0
    low, high = driver.lag_days
    return low <= gap <= high


class EvidenceRetriever:
    """BM25 over the corpus, with dual dates, a timing gate and noisy-OR corroboration."""

    def __init__(self, documents: list[Document]) -> None:
        self._documents = list(documents)
        self._corpus = [tokenise(f"{item.title} {item.body}") for item in self._documents]
        self._index = BM25Okapi(self._corpus) if self._corpus else None

    def retrieve(
        self,
        query: str,
        *,
        effect_day: dt.date,
        driver: ExogenousDriver | None = None,
        entities: list[str] | None = None,
        floor: float = EVIDENCE_FLOOR_DEFAULT,
        limit: int = 6,
    ) -> EvidenceBundle:
        """Retrieve, gate on timing, score, deduplicate by syndication, corroborate."""
        if self._index is None:
            return EvidenceBundle(floor=floor, detail="the corpus is empty")
        scores = self._index.get_scores(tokenise(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        # Normalise against the best *positive* score. BM25 returns negative scores for
        # terms carried by more than half the corpus, and dividing by a negative best
        # would invert the ranking as well as the sign.
        best = float(scores[ranked[0]]) if scores.size and scores[ranked[0]] > 0.0 else 1.0

        items: list[EvidenceItem] = []
        rejected: list[str] = []
        for position in ranked[:MAX_CANDIDATES]:
            document = self._documents[position]
            if not within_lag_profile(document, effect_day, driver):
                rejected.append(document.doc_id)
                continue
            items.append(
                EvidenceItem(
                    document=document,
                    rerank=float(min(1.0, max(0.0, scores[position] / best))),
                    source_tier_score=TIER_SCORE[document.source_tier],
                    entity_link=_entity_link(document, entities or []),
                    extraction=_extraction_quality(document),
                    matched_on=(
                        "effective_date"
                        if document.effective_date != document.publish_date
                        else "publish_date"
                    ),
                )
            )
        items.sort(key=lambda item: item.confidence, reverse=True)
        kept = _deduplicate(items)[:limit]
        corroboration = noisy_or([item.confidence for item in kept])
        bundle = EvidenceBundle(
            items=kept,
            rejected_by_timing=rejected,
            corroboration=corroboration,
            independent_sources=len({item.independence_key for item in kept}),
            floor=floor,
            detail=(
                f"{len(kept)} document(s) from {len({i.independence_key for i in kept})} "
                f"independent source(s) give corroboration {corroboration:.2f} against a "
                f"floor of {floor:.2f}; {len(rejected)} eliminated by the timing gate"
            ),
        )
        logger.info(
            "evidence.retrieved",
            kept=len(kept),
            rejected_by_timing=len(rejected),
            corroboration=corroboration,
            sufficient=bundle.sufficient,
        )
        return bundle


def _deduplicate(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Keep the strongest copy of each syndicated story. **The independence guard.**"""
    seen: set[str] = set()
    kept: list[EvidenceItem] = []
    for item in items:
        if item.independence_key in seen:
            continue
        seen.add(item.independence_key)
        kept.append(item)
    return kept


def _entity_link(document: Document, entities: list[str]) -> float:
    """How confidently this document is about the things the question is about."""
    if not entities:
        return 0.5
    haystack = f"{document.title} {document.body}".lower()
    hits = sum(1 for entity in entities if entity.lower() in haystack)
    return float(hits / len(entities))


def _extraction_quality(document: Document) -> float:
    """How reliably a fact can be pulled out of this document.

    A structured incident ticket yields a clean fact; a long free-text weekly review
    yields an inference. Length is a crude proxy and it is a *documented* crude proxy:
    the alternative is a learned extractor with no labels to train it on.
    """
    base = 0.9 if document.kind in ("ops_incident", "pricing_memo", "campaign_brief") else 0.6
    length_penalty = min(0.2, math.log1p(len(document.body)) / 60.0)
    return float(max(0.3, base - length_penalty))
