"""Governance blocks of the KPI contract: materiality, confidence, access, policy.

These are the parts a business owner edits. They are separated from the structural
model (grain, calculation, lineage, drivers) because they change on a different
cadence and for different reasons — a materiality floor moves when the business
changes its mind, a grain moves when the warehouse changes shape.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from insight_copilot.contracts.common import SQL_FRAGMENT_FORBIDDEN, StrictModel


class StatisticalMateriality(StrictModel):
    """The statistical half of the materiality gate."""

    method: str
    alpha: float = Field(default=0.01, gt=0, lt=1, description="Conformal alert threshold.")
    fdr_q: float = Field(default=0.05, gt=0, lt=1)
    shift_persistence_days: int = Field(default=3, ge=1)
    z_threshold: float | None = Field(
        default=None, description="Robust-z fallback when the conformal window is too short."
    )


class BusinessMateriality(StrictModel):
    """The business half. Both halves must trigger before anything is investigated."""

    min_abs_impact_inr: float | None = None
    min_pct_move: float | None = None
    min_abs_move_pp: float | None = None
    min_spend_at_risk_inr: float | None = None
    escalate_if_below_pct: float | None = None

    @model_validator(mode="after")
    def _at_least_one_floor(self) -> BusinessMateriality:
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("business materiality must set at least one floor")
        return self


class Materiality(StrictModel):
    """Statistical trigger AND business floor, plus the priority formula."""

    statistical: StatisticalMateriality
    business: BusinessMateriality
    priority_formula: str | None = None


class HardGates(StrictModel):
    """Conditions that force INSUFFICIENT regardless of the calibrated score."""

    any_signal_min: float = Field(default=0.30, ge=0, le=1)
    required_sources_fresh: bool = True
    reconciliation_within_tolerance: bool = False
    no_open_restatement_on_flagged_periods: bool = False
    lag_awareness: str | None = None


class ConfidencePolicy(StrictModel):
    """History floors, tier boundaries and the hard gates for this KPI."""

    min_history_days_full_stats: int = Field(ge=1)
    abstain_below: float = Field(ge=0, le=1)
    hedge_below: float = Field(ge=0, le=1)
    evidence_floor: float = Field(default=0.35, ge=0, le=1)
    hard_gates: HardGates = Field(default_factory=HardGates)

    @model_validator(mode="after")
    def _bands_ordered(self) -> ConfidencePolicy:
        if self.abstain_below >= self.hedge_below:
            raise ValueError("abstain_below must be strictly less than hedge_below")
        return self


class ColumnPolicy(StrictModel):
    """Which measures this role may see as values rather than as a MASKED sentinel."""

    mask: list[str] = Field(default_factory=list)


class RolePolicy(StrictModel):
    """One role's entitlement to one contract.

    ``rows`` is a filter TEMPLATE containing named bind parameters (``:user_region``).
    The template is contract-authored and validated; the *value* comes from the
    session and is bound, never interpolated.
    """

    deny: bool = False
    reason: str | None = None
    rows: str = "all"
    columns: ColumnPolicy = Field(default_factory=ColumnPolicy)
    national_headline: Literal["full", "summary_only"] = "full"
    note: str | None = None

    @field_validator("columns", mode="before")
    @classmethod
    def _coerce_all(cls, value: Any) -> Any:
        """``columns: all`` in YAML reads more naturally than ``columns: {mask: []}``."""
        if value == "all":
            return ColumnPolicy()
        return value

    @field_validator("rows")
    @classmethod
    def _row_filter_shape(cls, value: str) -> str:
        if value == "all":
            return value
        if SQL_FRAGMENT_FORBIDDEN.search(value):
            raise ValueError("row filter may not contain ';' or a SQL comment")
        if ":" not in value:
            raise ValueError(
                "a row filter must bind a session value by name, e.g. 'region = :user_region'"
            )
        return value

    @model_validator(mode="after")
    def _denial_states_a_reason(self) -> RolePolicy:
        if self.deny and not self.reason:
            raise ValueError("a denying policy must carry a reason shown to the user")
        return self


class AuditPolicy(StrictModel):
    """What is logged and for how long."""

    log_queries: bool = True
    log_narratives: bool = True
    retention_days: int = Field(default=365, ge=1)


class AccessPolicy(StrictModel):
    """Row-, column- and domain-level control, enforced in the compiler."""

    classification: str
    roles: dict[str, RolePolicy]
    audit: AuditPolicy = Field(default_factory=AuditPolicy)


class DriftChecks(StrictModel):
    """Input and coefficient drift watches."""

    input_psi_monthly: float | None = None
    coefficient_stability_refit_days: int | None = None


class Monitoring(StrictModel):
    """Freshness SLA and drift watches for this KPI."""

    freshness_sla_hours: float = Field(gt=0)
    drift_checks: DriftChecks = Field(default_factory=DriftChecks)


class Graduation(StrictModel):
    """When a sparse series earns access to the full statistical path."""

    full_stats_n: int = Field(ge=1)
    weekly_seasonality_n: int | None = None


class SparseHistoryPolicy(StrictModel):
    """What to do below ``min_history``: pool, do not extrapolate.

    WHY pooled empirical Bayes rather than a wider band on the series itself: with
    18 days you cannot estimate weekly seasonality from 2.5 cycles. Borrowing the
    shape from comparable launches is the only honest baseline, and the tier is
    capped so the language matches the evidence.
    """

    method: Literal["hierarchical_pool", "channel_pool", "warehouse_pool", "none"]
    pool_by: list[str] = Field(default_factory=list)
    guardrail_only_below_n: int = Field(ge=0)
    graduation: Graduation | None = None
