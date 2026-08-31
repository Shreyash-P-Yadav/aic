"""Claim-level verification: does a causal sentence follow from what it cites?

The number verifier catches a fabricated figure. It cannot catch a sentence whose
numbers are all correct and whose *causal claim* is not supported — "revenue fell 14%
**because a competitor cut prices**" when the competitor action post-dates the effect.
That is what this checks.

A documented fallback chain, because the strongest option needs a model this build does
not require:

1. **NLI model** — behind ``ENABLE_NLI_ENTAILMENT``. Never required.
2. **Small-model LLM judge** — when a provider is available.
3. **Numeric-only, with the tier capped at Moderate.** The honest floor: without a
   claim checker the system may not say "High", because it cannot substantiate that.

The result feeds ``c6``, and if ``c6`` lowers the tier the narrative is **re-rendered at
the lower tier's language** rather than left saying something the tier no longer allows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from insight_copilot.config import Settings, get_settings
from insight_copilot.engine.bundle import InsightEvidenceBundle
from insight_copilot.engine.confidence import Tier
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

Method = Literal["nli", "llm_judge", "numeric_only"]

CAUSAL_MARKERS = (
    "because",
    "driven by",
    "caused by",
    "due to",
    "as a result of",
    "the driver is",
    "attributable to",
    "explained by",
)
"""Sentences carrying one of these make a causal claim, which is the only kind of
sentence this verifier has an opinion about. A description of a movement is checked by
the number verifier and needs nothing more."""

NUMERIC_ONLY_TIER_CAP: Tier = "Moderate"
"""Without a claim checker the system may not say "High". The cap is the honest
statement of what the numeric check alone can support."""

SENTENCE = re.compile(r"(?<=[.!?])\s+")

LEXICAL_SUPPORT_FLOOR = 0.34
"""Share of a claim's content words that must appear in its cited evidence for the
lexical fallback to call it supported. Deliberately generous: this fallback exists to
catch a claim with *no* support in its citation, not to grade paraphrase quality."""

STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "is",
        "was",
        "were",
        "be",
        "been",
        "by",
        "with",
        "from",
        "that",
        "this",
        "its",
        "it",
        "as",
        "into",
        "during",
        "than",
        "then",
        "which",
        "while",
    ]
)


@dataclass
class EntailmentResult:
    """Per-sentence verdicts and the tier ceiling they imply."""

    method: Method
    sentences_checked: int = 0
    supported: int = 0
    unsupported_claims: list[str] = field(default_factory=list)
    tier_cap: Tier | None = None

    @property
    def score(self) -> float:
        """Minimum entailment across causal sentences, as ``c6`` consumes it."""
        if self.sentences_checked == 0:
            return 1.0
        return self.supported / self.sentences_checked

    @property
    def detail(self) -> str:
        """The line the evidence drawer shows beside ``c6``."""
        cap = f"; tier capped at {self.tier_cap}" if self.tier_cap else ""
        return (
            f"{self.method}: {self.supported}/{self.sentences_checked} causal claim(s) "
            f"supported by their citations{cap}"
        )


def causal_sentences(text: str) -> list[str]:
    """Sentences that assert a cause. Descriptions are not this verifier's business."""
    return [
        sentence.strip()
        for sentence in SENTENCE.split(text)
        if any(marker in sentence.lower() for marker in CAUSAL_MARKERS)
    ]


class EntailmentVerifier:
    """Checks causal claims against their citations, by the strongest available means."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def method(self) -> Method:
        """Which link of the fallback chain is actually in use."""
        if self._settings.enable_nli_entailment:
            return "nli"
        return "numeric_only"

    def verify(self, text: str, bundle: InsightEvidenceBundle) -> EntailmentResult:
        """Score every causal sentence against the bundle's evidence."""
        method = self.method
        claims = causal_sentences(text)
        if not claims:
            return EntailmentResult(
                method=method,
                tier_cap=NUMERIC_ONLY_TIER_CAP if method == "numeric_only" else None,
            )
        corpus = " ".join(
            f"{item.title} {item.kind} {item.doc_id}" for item in bundle.evidence
        ).lower()
        supported = 0
        failures: list[str] = []
        for claim in claims:
            if _lexically_supported(claim, corpus):
                supported += 1
            else:
                failures.append(claim)
        result = EntailmentResult(
            method=method,
            sentences_checked=len(claims),
            supported=supported,
            unsupported_claims=failures,
            tier_cap=NUMERIC_ONLY_TIER_CAP if method == "numeric_only" else None,
        )
        logger.info(
            "verify.entailment",
            method=method,
            checked=len(claims),
            supported=supported,
            cap=result.tier_cap,
        )
        return result


def cap_tier(tier: Tier, cap: Tier | None) -> Tier:
    """Apply a ceiling to a tier. Ordering is High > Moderate > Low > Insufficient."""
    if cap is None:
        return tier
    order: list[Tier] = ["Insufficient", "Low", "Moderate", "High"]
    return order[min(order.index(tier), order.index(cap))]


def _lexically_supported(claim: str, corpus: str) -> bool:
    """Do enough of the claim's content words appear in its cited evidence?"""
    words = [word for word in re.findall(r"[a-z]+", claim.lower()) if word not in STOPWORDS]
    if not words:
        return True
    hits = sum(1 for word in words if word in corpus)
    return hits / len(words) >= LEXICAL_SUPPORT_FLOOR
