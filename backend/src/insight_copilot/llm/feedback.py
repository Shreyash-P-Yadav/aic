"""Call site ④ — the feedback classifier. Offline, batched, never on the critical path.

An operator's free-text reaction to an insight ("we already knew this", "wrong region")
is the only labelled signal this system ever gets, and it is the input to P11's ranker
and calibration. Classifying it with a model is appropriate — it is language, not
arithmetic — and doing it in a batch, offline, means a slow or absent model degrades the
learning loop rather than the product.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from insight_copilot.contracts.common import StrictModel
from insight_copilot.errors import LLMError
from insight_copilot.llm.planner import _strip_fences
from insight_copilot.llm.router import ModelRouter
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

Label = Literal["useful", "already_known", "wrong_cause", "not_material"]
"""Four labels because they are the four different things a reader means, and each
implies a different correction: keep, deprioritise, re-attribute, raise the floor."""

SYSTEM = """Classify one reader's reaction to an analytical insight into exactly one of:
useful, already_known, wrong_cause, not_material. Return only JSON:
{"label": ..., "reason": ...}"""

RULES: tuple[tuple[Label, tuple[str, ...]], ...] = (
    ("already_known", ("already knew", "we know", "old news", "expected this")),
    ("wrong_cause", ("wrong", "not the cause", "actually", "misattributed", "incorrect")),
    ("not_material", ("too small", "noise", "immaterial", "not worth")),
    ("useful", ("useful", "helpful", "acted", "good catch", "thanks")),
)
"""A deterministic fallback so the learning loop works with no model at all. Ordered so
the more specific complaints are matched before the generic approval."""


class FeedbackLabel(StrictModel):
    """One classified reaction."""

    label: Label
    reason: str = ""


@dataclass(frozen=True)
class ClassifiedFeedback:
    """A reaction, its label, and how the label was reached."""

    insight_id: str
    text: str
    label: Label
    reason: str
    method: str


class FeedbackClassifier:
    """Labels reader feedback, by model when one is available and by rules otherwise."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self._router = router

    def classify_batch(self, items: list[tuple[str, str]]) -> list[ClassifiedFeedback]:
        """Classify ``(insight_id, text)`` pairs. Batched because it is never urgent."""
        return [self.classify(insight_id, text) for insight_id, text in items]

    def classify(self, insight_id: str, text: str) -> ClassifiedFeedback:
        """One reaction. Falls back to rules on any model failure, and says so."""
        if self._router is not None and self._router.provider.available:
            try:
                response = self._router.complete(
                    call_site="classify_feedback", system=SYSTEM, user=text
                )
                parsed = FeedbackLabel.model_validate(json.loads(_strip_fences(response.text)))
                return ClassifiedFeedback(
                    insight_id=insight_id,
                    text=text,
                    label=parsed.label,
                    reason=parsed.reason,
                    method="model",
                )
            except (LLMError, json.JSONDecodeError, ValidationError) as exc:
                logger.warning("feedback.model_failed", error=str(exc))
        label, reason = _by_rules(text)
        return ClassifiedFeedback(
            insight_id=insight_id, text=text, label=label, reason=reason, method="rules"
        )


def _by_rules(text: str) -> tuple[Label, str]:
    """The deterministic classifier. Unmatched feedback is ``useful`` by default.

    Defaulting to ``useful`` is deliberate: an unrecognised reaction should not
    silently deprioritise an insight, which is what any of the other three labels would
    do to the ranker.
    """
    lowered = text.lower()
    for label, markers in RULES:
        for marker in markers:
            if marker in lowered:
                return label, f"matched {marker!r}"
    return "useful", "no complaint marker found"
