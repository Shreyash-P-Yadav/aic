"""Pre-warming the narrative cache before the demo serves its first request.

A judge clicking through four scenarios should never wait on a model round trip, and
the router's semantic cache is keyed on ``(intent, watermark, contract_version)`` — all
of which are known the moment the pipeline finishes. So every persona's narrative for
every stored insight is rendered once, at startup, into the same cache the request path
reads.

This is also a **degradation test that runs in production**: pre-warming exercises the
narrator, the number verifier and the entailment check for every persona before anyone
is watching, so a provider that is missing, slow or wrong shows up as a startup line
rather than as a blank panel mid-demo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from insight_copilot.api.state import AppState
from insight_copilot.errors import LLMError
from insight_copilot.llm.narrate import PersonaNarrator
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

PERSONAS = ("cfo", "analyst", "rsm", "marketing_lead")
"""Every persona the UI can switch to. All four are warmed, because switching persona
is one click and a cold one is the only slow path a viewer would ever meet."""


@dataclass(frozen=True)
class PrewarmResult:
    """What pre-warming rendered, and what it could not."""

    rendered: int
    failed: int
    unverified: int
    elapsed_ms: float

    @property
    def detail(self) -> str:
        """The startup line."""
        parts = [f"{self.rendered} narrative(s) cached in {self.elapsed_ms:,.0f} ms"]
        if self.unverified:
            parts.append(f"{self.unverified} fell back to the template after verification")
        if self.failed:
            parts.append(f"{self.failed} could not be rendered at all")
        return "; ".join(parts)


def prewarm(state: AppState) -> PrewarmResult:
    """Render and cache every persona's narrative for every stored insight.

    Never raises. A pre-warm that fails leaves the request path exactly where it was —
    rendering on demand — so a missing provider degrades the demo's latency, not its
    correctness.
    """
    started = time.perf_counter()
    narrator = PersonaNarrator(state.router)
    rendered = failed = unverified = 0
    for record in state.insights.values():
        for persona in PERSONAS:
            try:
                if record.bundle is not None:
                    narrative = narrator.narrate(record.bundle, persona)
                elif record.abstention is not None:
                    narrative = narrator.narrate_abstention(record.abstention, persona)
                else:
                    continue
            except LLMError as exc:
                failed += 1
                logger.warning("prewarm.failed", persona=persona, error=str(exc))
                continue
            rendered += 1
            if narrative.source != "model":
                unverified += 1
    result = PrewarmResult(
        rendered=rendered,
        failed=failed,
        unverified=unverified,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )
    logger.info("prewarm.complete", rendered=rendered, failed=failed)
    return result
