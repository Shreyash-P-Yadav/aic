"""``LLMProvider`` — the only place a model is called, and the mock that makes it optional.

**`LLM_PROVIDER=mock` must run the entire application end to end with no API key and no
network.** That is a hard requirement and it is not a testing convenience: it protects
development cost, makes every test deterministic, and means demo day does not depend on
somebody else's uptime.

Four call sites exist and no more:

1. **Query planner** — receives structured facts only. No documents, no confidential
   values. Returns a typed plan validated against a domain allowlist.
2. **Hypothesis proposer** — cite-or-drop. A claim with no bundle document reference is
   dropped before it is scored. Proposes only; never sets a number.
3. **Persona narrator** — lazy, cached on ``(bundle_hash, persona, contract_version)``.
4. **Feedback classifier** — offline and batched, never on the critical path.

Nothing else in this system talks to a model, which is what makes "the LLM cannot emit
SQL and cannot produce a number" an architectural fact rather than a prompt instruction.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from insight_copilot.config import Settings, get_settings
from insight_copilot.errors import LLMError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

CallSite = Literal["planner", "hypotheses", "narrate", "classify_feedback", "intent"]
"""The four call sites, plus the conversational intent parser that reuses the planner's
small model. A caller that is not one of these has no business here."""

ModelTier = Literal["small", "mid"]

MOCK_LATENCY_TOKENS = 180
"""Nominal completion size the mock reports, so the cost meter has something to meter."""


@dataclass(frozen=True)
class LLMRequest:
    """One model call. Frozen, hashable, and the key of the semantic cache."""

    call_site: CallSite
    system: str
    user: str
    tier: ModelTier = "small"
    max_tokens: int = 900
    temperature: float = 0.0
    cache_key: str | None = None

    @property
    def digest(self) -> str:
        """Content hash used by the router's cache when no explicit key is given."""
        payload = json.dumps(
            {
                "call_site": self.call_site,
                "system": self.system,
                "user": self.user,
                "tier": self.tier,
            },
            sort_keys=True,
        )
        return hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()


@dataclass(frozen=True)
class LLMResponse:
    """One completion, plus what it cost."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cached: bool = False
    degraded_from: str | None = None
    """Set when the router downshifted the tier or fell back to templates."""


@dataclass
class ProviderStats:
    """What a provider has been asked to do. Read by the telemetry meter."""

    calls: int = 0
    by_call_site: dict[str, int] = field(default_factory=dict)

    def record(self, call_site: str) -> None:
        """Count one call."""
        self.calls += 1
        self.by_call_site[call_site] = self.by_call_site.get(call_site, 0) + 1


class LLMProvider(ABC):
    """A model behind one method. Injected everywhere, imported nowhere."""

    name: str = "provider"

    def __init__(self) -> None:
        self.stats = ProviderStats()

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a completion, or raise ``LLMError``. Never returns a number to trust."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """Can this provider actually be called right now?

        An unavailable provider is not an exception: the narrator degrades to templates,
        which is why the application is demonstrable with no model at all.
        """


class MockProvider(LLMProvider):
    """Deterministic, offline, and realistic enough to exercise every verifier.

    Its outputs are keyed by call site and by a digest of the request, so the same
    request always produces the same text — which is what lets the cache test assert a
    hit rather than assert that two similar strings look alike.
    """

    name = "mock"

    def __init__(self, *, canned: dict[str, str] | None = None) -> None:
        super().__init__()
        self._canned = dict(canned or {})

    @property
    def available(self) -> bool:
        """Always. That is the point of it."""
        return True

    @staticmethod
    def _default(request: LLMRequest) -> str:
        """The deterministic output for a call site with nothing canned."""
        if request.call_site == "narrate":
            try:
                draft = str(json.loads(request.user).get("draft", "")).strip()
            except (json.JSONDecodeError, AttributeError):
                draft = ""
            if draft:
                return f"In short: {draft}"
        return _DEFAULT_MOCK[request.call_site]

    def set_response(self, call_site: CallSite, text: str) -> None:
        """Override one call site's output — how a test injects a wrong number."""
        self._canned[call_site] = text

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the canned output for this call site, or a generic realistic one.

        For narration the mock *rewrites the draft it was handed*, which is what a
        well-behaved model does and what the narrator's contract asks for. A mock that
        returned unrelated prose would send every narration down the fallback path and
        the happy path would never be exercised by any test.
        """
        self.stats.record(request.call_site)
        text = self._canned.get(request.call_site) or self._default(request)
        return LLMResponse(
            text=text,
            model="mock-deterministic",
            input_tokens=len(request.system.split()) + len(request.user.split()),
            output_tokens=MOCK_LATENCY_TOKENS,
        )


class AnthropicProvider(LLMProvider):
    """The real provider. Constructed lazily so importing this module needs no key."""

    name = "anthropic"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings or get_settings()
        self._client: object | None = None

    @property
    def available(self) -> bool:
        """False with no API key, which degrades the narrator rather than crashing it."""
        return bool(self._settings.anthropic_api_key)

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Call the model, or raise ``LLMError`` the router converts into a degradation."""
        if not self.available:
            raise LLMError(
                "no Anthropic API key configured",
                detail="set ANTHROPIC_API_KEY, or run with LLM_PROVIDER=mock",
            )
        client = self._ensure_client()
        model = (
            self._settings.llm_model_small
            if request.tier == "small"
            else self._settings.llm_model_mid
        )
        self.stats.record(request.call_site)
        try:
            message = client.messages.create(  # type: ignore[attr-defined]  # lazy SDK import
                model=model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
            )
        except Exception as exc:
            raise LLMError(f"{model} call failed", detail=str(exc)) from exc
        return LLMResponse(
            text="".join(block.text for block in message.content if block.type == "text"),
            model=model,
            input_tokens=int(message.usage.input_tokens),
            output_tokens=int(message.usage.output_tokens),
        )

    def _ensure_client(self) -> object:
        """Import and construct the SDK on first use, never at import time."""
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        return self._client


def build_provider(settings: Settings | None = None) -> LLMProvider:
    """The provider the settings ask for. ``mock`` is the default and always works."""
    config = settings or get_settings()
    if config.llm_provider == "mock":
        return MockProvider()
    provider = AnthropicProvider(config)
    if not provider.available:
        logger.warning("llm.no_api_key", provider=config.llm_provider)
    return provider


_DEFAULT_MOCK: dict[str, str] = {
    "planner": json.dumps(
        {
            "intent": "explain_movement",
            "kpi_id": "net_revenue",
            "dimensions": ["region", "channel"],
            "drivers": ["fill_rate", "price_index"],
            "document_kinds": ["ops_incident", "pricing_memo"],
            "rationale": "A fulfilment shortfall concentrated in one region.",
        }
    ),
    "hypotheses": json.dumps(
        {
            "hypotheses": [
                {
                    "driver_id": "fill_rate",
                    "claim": "A pick-capacity failure at DC-North cut servable demand.",
                    "cites": ["DOC-OPS-0001"],
                },
                {
                    "driver_id": "price_index",
                    "claim": "A list-price increase reduced volume in the same window.",
                    "cites": ["DOC-MEMO-0001"],
                },
                {
                    "driver_id": "competitor_price_index",
                    "claim": "A competitor promotion took share.",
                    "cites": [],
                },
            ]
        }
    ),
    "narrate": (
        "Net revenue fell 40.32% against its counterfactual in the week to 15 March, a "
        "shortfall of 10,000,000 rupees. The movement is concentrated in North, which "
        "accounts for 51% of the gap. Fulfilment is the driver: a pick-capacity failure "
        "at DC-North cut servable demand, and the volume effect of 22,614,746 dominates "
        "a price effect of -926,696."
    ),
    "classify_feedback": json.dumps({"label": "useful", "reason": "acted on"}),
    "intent": json.dumps({"intent": "explain_movement", "kpi_id": "net_revenue"}),
}
"""Deterministic outputs, one per call site. The narration deliberately contains
numbers so the verifier has something real to check — and a test can corrupt one of
them to prove the check bites."""
