"""A complete zero-LLM narrator, for every persona and every tier.

**The application must be fully demonstrable with no model available.** That is not a
fallback in the apologetic sense: a template narrator cannot produce an unsupported
number, because it only interpolates facts out of the bundle. It is the *safest*
narrator in the system, and the model's job is to make the prose better, not truer.

Persona style cards are YAML because tone, length, permitted elements and number format
are governance — what a role is entitled to be told and in what form — rather than
prompt-craft.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from insight_copilot.contracts.common import StrictModel
from insight_copilot.engine.bundle import AbstentionArtifact, InsightEvidenceBundle
from insight_copilot.engine.confidence import Tier
from insight_copilot.errors import ContractError

PERSONA_DIR = Path(__file__).resolve().parent / "personas"

NumberFormat = Literal["plain", "lakh", "crore"]

CRORE = 10_000_000.0
LAKH = 100_000.0


class PersonaCard(StrictModel):
    """One role's narrative entitlement: tone, length, and what must and must not appear."""

    persona: str
    display_name: str
    tone: str
    max_sentences: int = Field(ge=1)
    number_format: NumberFormat = "plain"
    required_elements: list[str] = Field(default_factory=list)
    forbidden_elements: list[str] = Field(default_factory=list)
    show_actions: bool = True
    tier_language: dict[str, str] = Field(default_factory=dict)

    def permits(self, tier: Tier) -> str:
        """What this tier allows this persona to be told. The tier constrains language."""
        return self.tier_language.get(tier, "reports the movement only")


def load_personas(directory: Path | None = None) -> dict[str, PersonaCard]:
    """Every style card on disk, keyed by persona."""
    root = directory or PERSONA_DIR
    cards: dict[str, PersonaCard] = {}
    for path in sorted(root.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise ContractError(f"unreadable persona card {path.name}", detail=str(exc)) from exc
        card = PersonaCard.model_validate(payload)
        cards[card.persona] = card
    if not cards:
        raise ContractError(f"no persona cards found in {root}")
    return cards


MONETARY_UNIT = "INR"
"""The only unit crore and lakh may be applied to. Everything else renders plainly."""


def format_amount(value: float, style: NumberFormat, unit: str = MONETARY_UNIT) -> str:
    """Render a quantity the way the persona reads it — **in its own unit**.

    A CFO reads crore, a regional manager reads lakh, an analyst reads the number. The
    *value* is identical in all three, which is what lets the verifier match any of them
    against the same fact.

    ``unit`` is not decoration. Applied blindly, the persona styles turned a count of
    units into "Rs 1.40 crore" — wrong on screen, and correctly rejected by the number
    verifier, which is how this was found. A non-monetary KPI is rendered plainly with
    its unit named, because there is no lakh of a fill rate.
    """
    if unit != MONETARY_UNIT:
        return f"{value:,.0f} {unit}" if unit else f"{value:,.0f}"
    if style == "crore":
        return f"Rs {value / CRORE:,.2f} crore"
    if style == "lakh":
        return f"Rs {value / LAKH:,.1f} lakh"
    return f"{value:,.0f}"


class TemplateNarrator:
    """Deterministic prose from the bundle. Never wrong, occasionally wooden."""

    def __init__(self, personas: dict[str, PersonaCard] | None = None) -> None:
        self._personas = personas or load_personas()

    @property
    def personas(self) -> list[str]:
        """Every persona with a style card."""
        return sorted(self._personas)

    def card(self, persona: str) -> PersonaCard:
        """One persona's card, or a typed error naming the ones that exist."""
        try:
            return self._personas[persona]
        except KeyError as exc:
            raise ContractError(
                f"unknown persona {persona!r}", detail=f"known: {', '.join(self.personas)}"
            ) from exc

    def narrate(self, bundle: InsightEvidenceBundle, persona: str) -> str:
        """The insight, in this persona's language and at this tier's permitted strength."""
        card = self.card(persona)
        tier = bundle.confidence.tier
        sentences = [self._headline(bundle, card)]
        if tier in ("High", "Moderate") and bundle.segments:
            top = bundle.segments[0]
            sentences.append(
                f"It is concentrated in {top.label}, which accounts for "
                f"{abs(top.explanatory_power):.0%} of the gap "
                f"(bootstrap win rate {top.stability:.0%})."
            )
        elif bundle.segments:
            shortlist = ", ".join(item.label for item in bundle.segments[:3])
            sentences.append(f"Candidate segments, ranked and unconfirmed: {shortlist}.")
        sentences.extend(self._method(bundle, card))
        sentences.append(
            f"Confidence is {tier} ({bundle.confidence.calibrated:.2f}"
            f"{'' if bundle.confidence.calibration_fitted else ', uncalibrated'}); "
            f"the weakest signal is {bundle.confidence.weakest_signal}."
        )
        if card.show_actions and bundle.actions:
            action = bundle.actions[0]
            sentences.append(
                f"Recommended: {action.title}. Expected impact "
                f"{format_amount(action.expected_impact_central, card.number_format)} "
                f"(interval {format_amount(action.expected_impact_low, card.number_format)} "
                f"to {format_amount(action.expected_impact_high, card.number_format)}); "
                f"owner {action.owner_role}."
            )
        return " ".join(sentences[: card.max_sentences])

    def narrate_abstention(self, artifact: AbstentionArtifact, persona: str) -> str:
        """The abstention, in this persona's language. It says what it does know."""
        card = self.card(persona)
        sentences = [
            f"{artifact.kpi_id} moved {artifact.observed_movement} in the period to "
            f"{artifact.period_end.isoformat()}, and is not attributed.",
            f"Blocking check: {artifact.failed_checks[0]}."
            if artifact.failed_checks
            else "No check passed.",
        ]
        if artifact.missing_evidence:
            sentences.append(f"Missing: {artifact.missing_evidence[0]}.")
        sentences.append(f"This will be retried on {artifact.retry_trigger}.")
        return " ".join(sentences[: card.max_sentences])

    def _headline(self, bundle: InsightEvidenceBundle, card: PersonaCard) -> str:
        """The first sentence. Every number in it is a bundle fact."""
        direction = "fell" if bundle.delta < 0 else "rose"
        delta = bundle.fact("delta")
        unit = delta.unit if delta else MONETARY_UNIT
        return (
            f"{bundle.kpi_id} {direction} {abs(bundle.delta_pct):.2f}% against its "
            f"counterfactual, a gap of "
            f"{format_amount(abs(bundle.delta), card.number_format, unit)}."
        )

    @staticmethod
    def _method(bundle: InsightEvidenceBundle, card: PersonaCard) -> list[str]:
        """Method detail, only for personas whose card permits it."""
        if "coefficients" in card.forbidden_elements or not bundle.drivers:
            return []
        leading = max(bundle.drivers, key=lambda item: abs(item.coefficient))
        return [
            f"The leading driver is {leading.driver_id} at {leading.coefficient:.3f} "
            f"(95% interval {leading.interval_low:.3f} to {leading.interval_high:.3f}, "
            f"estimator agreement {leading.agreement:.2f}); "
            f"{bundle.explained_fraction:.0%} of the variation is explained and "
            f"{bundle.unexplained_fraction:.0%} is not."
        ]
