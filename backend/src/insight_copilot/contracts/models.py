"""KPI semantic contract — the model of *meaning*.

A KPI contract is executable governance. The compiler builds SQL from
``calculation`` and the caller's entitlements from ``access``; the engine reads
``drivers``, ``materiality``, ``confidence_policy`` and ``sparse_history_policy``;
the UI renders ``lineage`` and ``definition``.

WHY every threshold lives here rather than in code: governance must be editable by
the business without a code change, and an audit needs to see which *version* of a
definition produced a number. A magic number in a Python module is neither.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from insight_copilot.contracts.common import (
    IDENTIFIER,
    SQL_FRAGMENT_FORBIDDEN,
    Aggregation,
    Calendar,
    DriverDirection,
    StrictModel,
    Unit,
)
from insight_copilot.contracts.governance import (
    AccessPolicy,
    ConfidencePolicy,
    Materiality,
    Monitoring,
    SparseHistoryPolicy,
)


class KPIMeta(StrictModel):
    """Who owns this metric and where it sits in the priority order."""

    id: str
    name: str
    tier: int = Field(ge=1, le=3, description="1 = headline; weights alert priority")
    business_owner: str
    data_steward: str
    description: str

    @field_validator("id")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not IDENTIFIER.match(value):
            raise ValueError(f"kpi.id must be snake_case: {value!r}")
        return value


class RatioSpec(StrictModel):
    """A ratio metric aggregates its numerator and denominator separately.

    WHY: averaging weekly ROAS values across weeks is not ROAS. Recording the two
    component measures makes the compiler build the correct aggregate.
    """

    numerator: str
    denominator: str


class Definition(StrictModel):
    """Grain, calendar, unit and the queryable dimension allowlist."""

    base_grain: list[str]
    default_reporting_grain: list[str]
    dimensions: list[str] = Field(
        description=(
            "Every dimension a caller may group or filter by, including conformed "
            "rollups (category, warehouse->region). This IS the compiler's allowlist."
        )
    )
    calendar: Calendar
    unit: Unit
    aggregation: Aggregation
    ratio_of: RatioSpec | None = None
    null_policy: str

    @field_validator("base_grain", "default_reporting_grain", "dimensions")
    @classmethod
    def _identifiers(cls, values: list[str]) -> list[str]:
        for value in values:
            if not IDENTIFIER.match(value):
                raise ValueError(f"dimension must be snake_case: {value!r}")
        return values

    @model_validator(mode="after")
    def _grain_within_dimensions(self) -> Definition:
        unknown = set(self.base_grain) - set(self.dimensions)
        if unknown:
            raise ValueError(f"base_grain not in dimensions allowlist: {sorted(unknown)}")
        return self

    @model_validator(mode="after")
    def _ratio_metrics_declare_components(self) -> Definition:
        if self.aggregation == "weighted" and self.ratio_of is None:
            raise ValueError("aggregation='weighted' requires ratio_of")
        return self


class Calculation(StrictModel):
    """The measure expression and the gold view it reads."""

    measure_sql: str
    source_view: str
    derived_submetrics: dict[str, str] = Field(default_factory=dict)

    @field_validator("measure_sql")
    @classmethod
    def _no_statement_break(cls, value: str) -> str:
        if SQL_FRAGMENT_FORBIDDEN.search(value):
            raise ValueError("measure_sql may not contain ';' or a SQL comment")
        return value

    @field_validator("derived_submetrics")
    @classmethod
    def _submetrics_safe(cls, value: dict[str, str]) -> dict[str, str]:
        for name, expression in value.items():
            if not IDENTIFIER.match(name):
                raise ValueError(f"submetric name must be snake_case: {name!r}")
            if SQL_FRAGMENT_FORBIDDEN.search(expression):
                raise ValueError(f"submetric {name!r} may not contain ';' or a comment")
        return value

    @field_validator("source_view")
    @classmethod
    def _qualified_view(cls, value: str) -> str:
        parts = value.split(".")
        if len(parts) != 2 or not all(IDENTIFIER.match(part) for part in parts):
            raise ValueError(f"source_view must be schema.table in snake_case: {value!r}")
        return value


class SourceRef(StrictModel):
    """A source this KPI depends on, and what its absence means."""

    source_id: str
    role: Literal["primary", "reconciliation"] = "primary"
    required: bool = True
    tolerance_pct: float | None = Field(
        default=None, description="Reconciliation tolerance; breaching it is a hard gate."
    )


class LineageStep(StrictModel):
    """One hop from a source system to the gold mart."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    step: Literal["land", "conform", "mart", "blend"]
    source: str | list[str] = Field(alias="from")
    target: str = Field(alias="to")
    transform: str


class ElasticityPrior(StrictModel):
    """A prior on a driver's elasticity.

    WHY a prior and not a fixed value: priors shape ranking and tie-breaks under thin
    data; they never override a significant contrary estimate, and the estimated
    coefficient with its CI is always what reaches the bundle.
    """

    mean: float
    sd: float = Field(gt=0)


class IdentityDriver(StrictModel):
    """A component of an exact arithmetic decomposition (Bennet PVM, or a ratio)."""

    id: str
    role: Literal["price", "quantity", "mix", "numerator", "denominator"]
    over: list[str] = Field(default_factory=list)


class ExogenousDriver(StrictModel):
    """A driver estimated econometrically, with its DAG role and lag profile."""

    id: str
    kpi_ref: str | None = Field(default=None, description="Cross-contract DAG edge.")
    direction: DriverDirection
    lag_days: tuple[int, int] = Field(
        default=(0, 0),
        description=(
            "Admissible cause-to-effect lag. The evidence timing gate eliminates any "
            "candidate whose date falls outside this window."
        ),
    )
    adstock_half_life_days: int | None = None
    controllable: bool = False
    lever: str | None = None
    elasticity_prior: ElasticityPrior | None = None
    coverage: Literal["full", "partial"] = "full"
    mediates: list[str] = Field(
        default_factory=list,
        description=(
            "Driver ids whose TOTAL effect flows through this one. Conditioning on a "
            "mediator blocks the effect being measured, so the design matrix excludes "
            "this regressor when any listed driver's total effect is the estimand."
        ),
    )
    source: str | None = None

    @model_validator(mode="after")
    def _controllable_drivers_have_levers(self) -> ExogenousDriver:
        if self.controllable and not self.lever:
            raise ValueError(f"driver {self.id!r} is controllable but names no lever")
        return self

    @model_validator(mode="after")
    def _lag_window_ordered(self) -> ExogenousDriver:
        if self.lag_days[0] > self.lag_days[1]:
            raise ValueError(f"driver {self.id!r} has an inverted lag_days window")
        return self


class FeedEdge(StrictModel):
    """This KPI is a leading indicator of another, with a lag."""

    kpi_ref: str
    lag_days: tuple[int, int] = (0, 0)


class DriverDAG(StrictModel):
    """The causal graph the attribution ladder is allowed to reason over."""

    identity: list[IdentityDriver] = Field(default_factory=list)
    exogenous: list[ExogenousDriver] = Field(default_factory=list)
    downstream_of: list[str] = Field(default_factory=list)
    feeds: list[FeedEdge] = Field(default_factory=list)

    def admissible_regressors(self, estimand: str) -> list[ExogenousDriver]:
        """Regressors admissible when estimating the TOTAL effect of ``estimand``.

        WHY exclude mediators: conditioning on the channel through which an effect
        travels blocks that effect. Estimating marketing's total effect on revenue
        while controlling for unit volume returns approximately zero and reads as a
        finding rather than a specification error.
        """
        return [d for d in self.exogenous if d.id != estimand and estimand not in d.mediates]


class KPIContract(StrictModel):
    """One governed metric, fully specified."""

    contract_version: str
    kpi: KPIMeta
    definition: Definition
    calculation: Calculation
    sources: list[SourceRef]
    lineage: list[LineageStep]
    drivers: DriverDAG
    materiality: Materiality
    confidence_policy: ConfidencePolicy
    access: AccessPolicy
    actions_ref: str | None = None
    monitoring: Monitoring
    sparse_history_policy: SparseHistoryPolicy

    @model_validator(mode="after")
    def _primary_source_exists(self) -> KPIContract:
        if not any(source.role == "primary" for source in self.sources):
            raise ValueError(f"{self.kpi.id}: no primary source declared")
        return self

    @property
    def required_source_ids(self) -> list[str]:
        """Sources whose freshness breach forces abstention."""
        return [source.source_id for source in self.sources if source.required]

    @property
    def maskable_columns(self) -> set[str]:
        """Every column any role masks — the set the compiler may substitute."""
        return {column for policy in self.access.roles.values() for column in policy.columns.mask}
