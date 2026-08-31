"""Cost and latency accounting per insight. The number the cost story rests on.

Every model call, cache hit and downgrade is recorded against the insight that caused
it, so "we spend about four paise per insight because work happens when data changes"
is a measurement rather than a claim. The meter is also what makes the router's cost cap
enforceable: the cap is checked against what has actually been spent on *this* insight,
not against a running total for the process.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from insight_copilot.llm.provider import LLMResponse
from insight_copilot.llm.router import estimate_cost
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

USD_TO_INR = 83.4
"""The same published policy rate the ingestion layer converts at, so a cost quoted in
rupees on the telemetry screen reconciles with one quoted in dollars."""


@dataclass
class CallRecord:
    """One model call, or one cache hit."""

    call_site: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool
    degraded_from: str | None
    at: dt.datetime


@dataclass
class InsightMeter:
    """What one insight cost, end to end."""

    insight_id: str
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def spend_usd(self) -> float:
        """Total spend. Cache hits contribute nothing, which is the point of them."""
        return sum(record.cost_usd for record in self.calls)

    @property
    def spend_inr(self) -> float:
        """The same number in rupees, at the published policy rate."""
        return self.spend_usd * USD_TO_INR

    @property
    def cache_hits(self) -> int:
        """Calls served without touching a model."""
        return sum(1 for record in self.calls if record.cached)

    @property
    def downgrades(self) -> int:
        """Times the cost cap forced a smaller model. Never silent."""
        return sum(1 for record in self.calls if record.degraded_from is not None)

    def record(
        self, call_site: str, response: LLMResponse, tier: str, *, at: dt.datetime
    ) -> CallRecord:
        """Add one call. Returns the record so a caller can log it."""
        cost = (
            0.0
            if response.cached
            else estimate_cost(tier, response.input_tokens, response.output_tokens)  # type: ignore[arg-type]
        )
        record = CallRecord(
            call_site=call_site,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost,
            cached=response.cached,
            degraded_from=response.degraded_from,
            at=at,
        )
        self.calls.append(record)
        return record

    @property
    def detail(self) -> str:
        """The telemetry line for one insight."""
        return (
            f"{len(self.calls)} model call(s), {self.cache_hits} served from cache, "
            f"{self.downgrades} downgraded; Rs {self.spend_inr:.3f} "
            f"(USD {self.spend_usd:.5f})"
        )


class TelemetryLedger:
    """Every insight's meter, and the aggregate the telemetry screen renders."""

    def __init__(self) -> None:
        self._meters: dict[str, InsightMeter] = {}

    def meter(self, insight_id: str) -> InsightMeter:
        """The meter for one insight, created on first use."""
        return self._meters.setdefault(insight_id, InsightMeter(insight_id=insight_id))

    @property
    def total_usd(self) -> float:
        """Spend across every metered insight."""
        return sum(meter.spend_usd for meter in self._meters.values())

    @property
    def mean_usd_per_insight(self) -> float:
        """The headline cost number. Zero when nothing has been metered."""
        return self.total_usd / len(self._meters) if self._meters else 0.0

    @property
    def insights(self) -> list[InsightMeter]:
        """Every meter, newest first by insight id."""
        return list(self._meters.values())

    def summary(self) -> str:
        """One line for the CLI and the telemetry screen."""
        return (
            f"{len(self._meters)} insight(s); mean USD {self.mean_usd_per_insight:.5f} "
            f"(Rs {self.mean_usd_per_insight * USD_TO_INR:.3f}); total USD {self.total_usd:.5f}"
        )
