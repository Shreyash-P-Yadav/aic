"""Model routing: tiering, caching and a cost cap that downshifts and **logs it**.

Three jobs, and the third is the one that matters on a bill:

* **Tier by call site.** A planner returning a small typed object does not need the same
  model as a four-paragraph narrative for a CFO.
* **Cache semantically**, on ``(intent_hash, data_watermark, contract_version)``. The
  watermark is in the key because the same question against restated data is a
  different question, and a cache that ignored it would serve yesterday's number with
  today's date on it.
* **Cap the cost per insight.** When the cap would be breached the router downshifts the
  tier and *logs the downgrade*, so a cheaper narrative is never mistaken for a
  considered one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from insight_copilot.config import Settings, get_settings
from insight_copilot.errors import LLMError
from insight_copilot.llm.provider import CallSite, LLMProvider, LLMRequest, LLMResponse, ModelTier
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

TIER_FOR_CALL_SITE: dict[str, ModelTier] = {
    "planner": "small",
    "intent": "small",
    "classify_feedback": "small",
    "hypotheses": "mid",
    "narrate": "mid",
}
"""Narration and hypothesis generation get the larger model; everything else is a
structured transformation a small model does as well and far more cheaply."""

PRICE_PER_MTOK = {"small": (1.0, 5.0), "mid": (3.0, 15.0)}
"""(input, output) USD per million tokens, by tier. Indicative list prices used to
enforce the per-insight cap; the meter records what was actually spent."""

MTOK = 1_000_000.0


@dataclass
class CacheEntry:
    """One cached completion and what it was keyed on."""

    key: str
    response: LLMResponse
    hits: int = 0


@dataclass
class RouterStats:
    """What the router did. Surfaced on the telemetry screen."""

    calls: int = 0
    cache_hits: int = 0
    downgrades: int = 0
    spend_usd: float = 0.0
    by_call_site: dict[str, int] = field(default_factory=dict)


class ModelRouter:
    """Chooses the model, serves the cache, and enforces the per-insight cost cap."""

    def __init__(self, provider: LLMProvider, settings: Settings | None = None) -> None:
        self._provider = provider
        self._settings = settings or get_settings()
        self._cache: dict[str, CacheEntry] = {}
        self.stats = RouterStats()

    @property
    def provider(self) -> LLMProvider:
        """The provider behind this router."""
        return self._provider

    def semantic_key(
        self, *, intent: str, watermark: str | None, contract_version: str, extra: str = ""
    ) -> str:
        """``(intent_hash, data_watermark, contract_version)`` — the design's own key."""
        payload = f"{intent}|{watermark or 'none'}|{contract_version}|{extra}"
        return hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()

    def complete(
        self,
        *,
        call_site: CallSite,
        system: str,
        user: str,
        cache_key: str | None = None,
        spent_usd: float = 0.0,
        max_tokens: int = 900,
    ) -> LLMResponse:
        """Route one call. Raises ``LLMError`` only when the provider is unusable."""
        tier, downgraded = self._tier_for(call_site, spent_usd)
        request = LLMRequest(
            call_site=call_site,
            system=system,
            user=user,
            tier=tier,
            max_tokens=max_tokens,
            cache_key=cache_key,
        )
        key = cache_key or request.digest
        cached = self._cache.get(key)
        if cached is not None:
            cached.hits += 1
            self.stats.cache_hits += 1
            logger.info("router.cache_hit", call_site=call_site, key=key[:8], hits=cached.hits)
            return LLMResponse(**{**vars(cached.response), "cached": True})

        if not self._provider.available:
            raise LLMError(
                f"{self._provider.name} is not available",
                detail="the narrator degrades to templates rather than failing the request",
            )
        response = self._provider.complete(request)
        if downgraded:
            response = LLMResponse(**{**vars(response), "degraded_from": "mid"})
        self._cache[key] = CacheEntry(key=key, response=response)
        self.stats.calls += 1
        self.stats.by_call_site[call_site] = self.stats.by_call_site.get(call_site, 0) + 1
        self.stats.spend_usd += estimate_cost(tier, response.input_tokens, response.output_tokens)
        logger.info(
            "router.completed",
            call_site=call_site,
            tier=tier,
            downgraded=downgraded,
            spend_usd=round(self.stats.spend_usd, 5),
        )
        return response

    def _tier_for(self, call_site: CallSite, spent_usd: float) -> tuple[ModelTier, bool]:
        """The tier this call site wants, downshifted if the cap is close."""
        wanted = TIER_FOR_CALL_SITE.get(call_site, "small")
        cap = self._settings.llm_cost_cap_usd_per_insight
        if wanted == "mid" and spent_usd >= cap:
            self.stats.downgrades += 1
            logger.warning(
                "router.downgraded",
                call_site=call_site,
                spent_usd=round(spent_usd, 5),
                cap_usd=cap,
                frm="mid",
                to="small",
            )
            return "small", True
        return wanted, False


def estimate_cost(tier: ModelTier, input_tokens: int, output_tokens: int) -> float:
    """USD for one call at list price. The meter records the real total."""
    price_in, price_out = PRICE_PER_MTOK[tier]
    return (input_tokens * price_in + output_tokens * price_out) / MTOK
