"""Call site ③ — the persona narrator, and the guard rails around it.

The sequence is the point:

1. Render a template narrative. It is always correct, and it is the floor.
2. Ask the model to improve it, given **only** the bundle's facts and the persona card.
3. Verify every number against the bundle. An unmatched number is a failure.
4. On failure, regenerate with the offending numbers named — at most twice.
5. Still failing? Return the template. **A sentence with an unsupported number never
   reaches a human.**
6. Verify the causal claims. If that caps the tier, **re-render at the lower tier's
   language** rather than leave prose the tier no longer permits.

Caching is on ``(bundle_hash, persona, contract_version)``, so a second reader of the
same insight in the same role costs nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from insight_copilot.engine.bundle import AbstentionArtifact, InsightEvidenceBundle
from insight_copilot.engine.confidence import Tier
from insight_copilot.errors import LLMError
from insight_copilot.llm.router import ModelRouter
from insight_copilot.llm.templates import PersonaCard, TemplateNarrator
from insight_copilot.llm.verify_entailment import EntailmentResult, EntailmentVerifier, cap_tier
from insight_copilot.llm.verify_numbers import MAX_REGENERATIONS, VerificationResult, verify
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

SYSTEM = """You rewrite a factual summary for one reader. You may reorder, compress and
improve the prose. You may NOT introduce, alter, round differently, or infer any number:
every figure in your output must appear in the facts you are given. You may not add a
cause that is not in the facts. Return prose only."""


@dataclass
class Narrative:
    """One rendered narrative and everything that was checked before it was returned."""

    text: str
    persona: str
    tier: Tier
    source: str
    """``model``, ``template``, or ``template_after_failed_verification``."""
    attempts: int = 1
    numbers: VerificationResult | None = None
    entailment: EntailmentResult | None = None
    cached: bool = False
    rejected_drafts: list[str] = field(default_factory=list)

    @property
    def faithfulness(self) -> float:
        """The ``c6`` input: every number checked, and every causal claim supported."""
        numeric = self.numbers.faithfulness if self.numbers else 1.0
        claims = self.entailment.score if self.entailment else 1.0
        return float(min(numeric, claims))

    @property
    def detail(self) -> str:
        """What the evidence drawer shows under the narrative."""
        parts = [f"rendered by {self.source} after {self.attempts} attempt(s)"]
        if self.numbers:
            parts.append(self.numbers.detail)
        if self.entailment:
            parts.append(self.entailment.detail)
        return "; ".join(parts)


class PersonaNarrator:
    """Narrates an insight for one persona, verifying before it returns."""

    def __init__(
        self,
        router: ModelRouter,
        templates: TemplateNarrator | None = None,
        entailment: EntailmentVerifier | None = None,
    ) -> None:
        self._router = router
        self._templates = templates or TemplateNarrator()
        self._entailment = entailment or EntailmentVerifier()
        self._cache: dict[str, Narrative] = {}

    @property
    def templates(self) -> TemplateNarrator:
        """The zero-LLM narrator. The application is demonstrable with only this."""
        return self._templates

    def narrate(
        self, bundle: InsightEvidenceBundle, persona: str, *, use_model: bool = True
    ) -> Narrative:
        """Render, verify, regenerate if needed, and cap the tier if claims fail."""
        card = self._templates.card(persona)
        key = self.cache_key(bundle, persona)
        cached = self._cache.get(key)
        if cached is not None:
            logger.info("narrate.cache_hit", persona=persona, insight_id=bundle.insight_id)
            return Narrative(**{**vars(cached), "cached": True})

        baseline = self._templates.narrate(bundle, persona)
        narrative = (
            self._with_model(bundle, card, baseline)
            if use_model and self._router.provider.available
            else Narrative(
                text=baseline,
                persona=persona,
                tier=bundle.confidence.tier,
                source="template",
                numbers=verify(baseline, bundle),
            )
        )
        narrative = self._apply_entailment(narrative, bundle, persona)
        self._cache[key] = narrative
        return narrative

    def narrate_abstention(self, artifact: AbstentionArtifact, persona: str) -> Narrative:
        """Abstentions are always templated. There is nothing here worth a model call."""
        text = self._templates.narrate_abstention(artifact, persona)
        return Narrative(
            text=text, persona=persona, tier=artifact.confidence.tier, source="template"
        )

    @staticmethod
    def cache_key(bundle: InsightEvidenceBundle, persona: str) -> str:
        """``(bundle_hash, persona, contract_version)`` — the design's own key."""
        payload = bundle.model_dump_json(exclude={"insight_id", "computed_at"})
        digest = hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()
        return f"{digest}:{persona}:{bundle.contract_version}"

    # ------------------------------------------------------------------ model --
    def _with_model(
        self, bundle: InsightEvidenceBundle, card: PersonaCard, baseline: str
    ) -> Narrative:
        """Improve the template, then verify. Two retries, then keep the template."""
        rejected: list[str] = []
        last: VerificationResult | None = None
        for attempt in range(1, MAX_REGENERATIONS + 2):
            try:
                response = self._router.complete(
                    call_site="narrate",
                    system=SYSTEM,
                    user=self._prompt(bundle, card, baseline, last),
                    cache_key=f"{self.cache_key(bundle, card.persona)}:attempt{attempt}",
                )
            except LLMError as exc:
                logger.warning("narrate.provider_failed", error=str(exc), persona=card.persona)
                break
            result = verify(response.text, bundle)
            if result.passed:
                return Narrative(
                    text=response.text,
                    persona=card.persona,
                    tier=bundle.confidence.tier,
                    source="model",
                    attempts=attempt,
                    numbers=result,
                    rejected_drafts=rejected,
                )
            rejected.append(response.text)
            last = result
            logger.warning(
                "narrate.verification_failed",
                persona=card.persona,
                attempt=attempt,
                detail=result.detail,
            )
        return Narrative(
            text=baseline,
            persona=card.persona,
            tier=bundle.confidence.tier,
            source="template_after_failed_verification" if rejected else "template",
            attempts=max(1, len(rejected)),
            numbers=verify(baseline, bundle),
            rejected_drafts=rejected,
        )

    def _apply_entailment(
        self, narrative: Narrative, bundle: InsightEvidenceBundle, persona: str
    ) -> Narrative:
        """Check the causal claims, and re-render if the tier has to come down."""
        result = self._entailment.verify(narrative.text, bundle)
        capped = cap_tier(bundle.confidence.tier, result.tier_cap)
        if capped == narrative.tier:
            return Narrative(**{**vars(narrative), "entailment": result})
        logger.info(
            "narrate.tier_capped",
            persona=persona,
            frm=narrative.tier,
            to=capped,
            method=result.method,
        )
        lowered = bundle.model_copy(
            update={"confidence": bundle.confidence.model_copy(update={"tier": capped})}
        )
        return Narrative(
            text=self._templates.narrate(lowered, persona),
            persona=persona,
            tier=capped,
            source="template_after_tier_cap",
            attempts=narrative.attempts,
            numbers=verify(self._templates.narrate(lowered, persona), lowered),
            entailment=result,
            rejected_drafts=narrative.rejected_drafts,
        )

    @staticmethod
    def _prompt(
        bundle: InsightEvidenceBundle,
        card: PersonaCard,
        baseline: str,
        failure: VerificationResult | None,
    ) -> str:
        """The facts, the style card, the draft — and, on a retry, exactly what was wrong."""
        payload = {
            "persona": card.persona,
            "tone": card.tone,
            "max_sentences": card.max_sentences,
            "number_format": card.number_format,
            "required_elements": card.required_elements,
            "forbidden_elements": card.forbidden_elements,
            "permitted_strength": card.permits(bundle.confidence.tier),
            "facts": {item.key: item.value for item in bundle.narratable_values},
            "segments": [item.label for item in bundle.segments[:3]],
            "draft": baseline,
        }
        if failure is not None:
            payload["correction"] = (
                f"Your previous draft was rejected. {failure.detail}. Every number must "
                f"be one of the values in 'facts'."
            )
        return json.dumps(payload, sort_keys=True, default=str)
