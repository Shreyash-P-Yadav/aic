"""Conform-time policies that are governance decisions rather than code.

Currency is the only one so far. It lives in YAML for the same reason KPI thresholds
do: which desk books in which currency, and at what rate-date, is a finance decision
that must be changeable and auditable without a release.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field

from insight_copilot.contracts.common import StrictModel
from insight_copilot.errors import ConfigError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

POLICY_DIR = Path(__file__).resolve().parent / "policies"
FX_POLICY_FILE = "fx_rates.yaml"


class ForeignUnit(StrictModel):
    """A business unit whose rows arrive denominated in something other than INR."""

    source_id: str
    unit_name: str
    currency: str
    where: dict[str, str]
    measures: list[str]
    plausibility_floor_inr: float = Field(gt=0)


class CurrencyPolicy(StrictModel):
    """The rate-date, the rates, and which units they apply to."""

    policy_rate_date: dt.date
    rates: dict[str, float]
    foreign_units: list[ForeignUnit] = Field(default_factory=list)

    def units_for(self, source_id: str) -> list[ForeignUnit]:
        """Declared foreign units for one source."""
        return [unit for unit in self.foreign_units if unit.source_id == source_id]

    def rate(self, currency: str) -> float:
        """Units of INR per unit of ``currency`` at the policy rate-date."""
        try:
            return self.rates[currency]
        except KeyError as exc:
            raise ConfigError(
                f"no published rate for {currency!r} at {self.policy_rate_date}"
            ) from exc


@lru_cache(maxsize=1)
def load_currency_policy(path: Path | None = None) -> CurrencyPolicy:
    """Read and validate the FX policy. Cached: it is read once per process."""
    source = path or (POLICY_DIR / FX_POLICY_FILE)
    try:
        payload = yaml.safe_load(source.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"unreadable currency policy {source}", detail=str(exc)) from exc
    policy = CurrencyPolicy.model_validate(payload)
    logger.info(
        "policy.currency_loaded",
        rate_date=policy.policy_rate_date.isoformat(),
        units=len(policy.foreign_units),
    )
    return policy
