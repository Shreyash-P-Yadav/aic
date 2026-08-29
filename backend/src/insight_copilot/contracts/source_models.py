"""Source contract — the model of *arrival*.

The KPI contract governs what a number means. The source contract governs when the
data shows up, in what shape, how late it may be, whether it revises itself, and
what "wrong" looks like. Ingestion is driven entirely by these files: there is no
hand-written loader per source, so adding a twelfth source is a YAML file rather
than a sprint.

WHY arrival deserves its own contract: every hard part of this problem — freshness,
restatement, reconciliation, abstention on stale feeds — lives in the arrival
process, not in the finished table. A system built against a complete warehouse
cannot express any of it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from insight_copilot.contracts.common import IDENTIFIER, QualityTier, StrictModel

Transport = Literal["sftp_drop", "s3_prefix", "api_pull", "db_replica", "file_watch"]
FileFormat = Literal["parquet", "csv", "json", "jsonl"]
ColumnType = Literal["string", "integer", "bigint", "decimal", "date", "timestamp", "boolean"]
DriftPolicy = Literal["quarantine_and_alert", "reject_batch", "accept_and_flag"]
RestatementPolicy = Literal["supersede_by_batch", "append_only", "none"]
BreachAction = Literal["block_attribution", "warn", "quarantine"]


class ArrivalSchedule(StrictModel):
    """When a batch is expected, and how unpunctual reality is allowed to be.

    WHY jitter and a failure probability are contract fields rather than test
    fixtures: real feeds are never punctual and sometimes simply do not come. If
    lateness only exists in tests, the freshness tracker is never exercised by the
    demo, and the abstention path stays theoretical.
    """

    cron: str = Field(description="Standard 5-field cron, evaluated in ``tz``.")
    tz: str = "Asia/Kolkata"
    jitter_minutes: int = Field(default=0, ge=0)
    failure_probability: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("cron")
    @classmethod
    def _five_fields(cls, value: str) -> str:
        if len(value.split()) != 5:
            raise ValueError(f"cron must have 5 fields: {value!r}")
        return value


class Covers(StrictModel):
    """The grain and period one batch of this source describes."""

    grain: list[str]
    period: Literal[
        "previous_day", "previous_iso_week", "previous_month", "t_minus_2", "continuous", "static"
    ]

    @field_validator("grain")
    @classmethod
    def _identifiers(cls, values: list[str]) -> list[str]:
        for value in values:
            if not IDENTIFIER.match(value):
                raise ValueError(f"grain column must be snake_case: {value!r}")
        return values


class Restatement(StrictModel):
    """Whether this source revises what it already sent, and how far back."""

    expected: bool = False
    window_days: int = Field(default=0, ge=0)
    policy: RestatementPolicy = "none"

    @model_validator(mode="after")
    def _restating_sources_declare_a_policy(self) -> Restatement:
        if self.expected and self.policy == "none":
            raise ValueError("a restating source must declare a supersession policy")
        if self.expected and self.window_days <= 0:
            raise ValueError("a restating source must declare a positive window_days")
        return self


class ColumnSpec(StrictModel):
    """One column's type and the expectations that make a defect detectable.

    ``min``/``max`` are the reason a silent paise-to-rupees unit change is caught
    rather than quietly changing every downstream number by 100x.
    """

    type: ColumnType
    pk: bool = False
    allowed: list[str] | None = None
    min: float | None = None
    max: float | None = None
    null_frac_max: float | None = Field(default=None, ge=0.0, le=1.0)
    pii: bool = Field(default=False, description="Masked at silver, before indexing.")
    description: str | None = None


class SchemaSpec(StrictModel):
    """The delivered shape, versioned, with a policy for unexpected columns."""

    version: int = Field(ge=1)
    columns: dict[str, ColumnSpec]
    drift_policy: DriftPolicy = "quarantine_and_alert"

    @field_validator("columns")
    @classmethod
    def _column_names(cls, value: dict[str, ColumnSpec]) -> dict[str, ColumnSpec]:
        for name in value:
            if not IDENTIFIER.match(name):
                raise ValueError(f"column must be snake_case: {name!r}")
        return value

    @model_validator(mode="after")
    def _has_a_primary_key(self) -> SchemaSpec:
        if not any(column.pk for column in self.columns.values()):
            raise ValueError("schema declares no primary-key columns")
        return self

    @property
    def primary_key(self) -> list[str]:
        """Columns forming the business key, used for dedup within a period."""
        return [name for name, column in self.columns.items() if column.pk]

    @property
    def pii_columns(self) -> list[str]:
        """Columns masked at silver. Sensitive strings never enter the index."""
        return [name for name, column in self.columns.items() if column.pii]


class Expectations(StrictModel):
    """Batch-level data-quality gates. Failures quarantine rows; they never drop them."""

    row_count_min: int | None = Field(default=None, ge=0)
    row_count_max: int | None = None
    monotonic_columns: list[str] = Field(default_factory=list)
    comparisons: list[str] = Field(
        default_factory=list,
        description=(
            "Declarative row predicates the ingest layer evaluates, e.g. "
            "'clicks <= impressions'. Column names are checked against the schema."
        ),
    )
    max_frac_violating: dict[str, float] = Field(
        default_factory=dict,
        description="Named expectation -> tolerated violating fraction before quarantine.",
    )


class ReconciliationCheck(StrictModel):
    """A cross-source agreement this pipeline is required to make.

    Living with the normal-range disagreement is the point; exceeding the tolerance
    is what makes the engine abstain rather than attribute.
    """

    against: str
    measure: str
    tolerance_pct: float = Field(gt=0)
    window: str
    on_breach: BreachAction = "warn"


class SourceContract(StrictModel):
    """One feed, fully specified from cron to classification."""

    source_id: str
    system: str
    owner: str
    transport: Transport
    format: FileFormat
    landing_path: str
    arrival: ArrivalSchedule
    latency_sla_hours: float = Field(gt=0)
    covers: Covers
    restatement: Restatement = Field(default_factory=Restatement)
    schema_spec: SchemaSpec = Field(alias="schema")
    watermark: str
    idempotency: list[str] = Field(default_factory=lambda: ["batch_id", "row_hash"])
    expectations: Expectations = Field(default_factory=Expectations)
    reconciliation: list[ReconciliationCheck] = Field(default_factory=list)
    history_available_months: int = Field(ge=1)
    known_issues: list[str] = Field(default_factory=list)
    classification: str
    quality_tier: QualityTier = "medium"
    build_tier: Literal["full", "lightweight", "corpus_only"] = "full"

    model_config = StrictModel.model_config | {"populate_by_name": True}

    @field_validator("source_id")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not IDENTIFIER.match(value):
            raise ValueError(f"source_id must be snake_case: {value!r}")
        return value

    @model_validator(mode="after")
    def _watermark_is_a_delivered_column(self) -> SourceContract:
        if self.watermark not in self.schema_spec.columns:
            raise ValueError(
                f"{self.source_id}: watermark {self.watermark!r} is not a delivered column"
            )
        return self

    @model_validator(mode="after")
    def _expectation_columns_exist(self) -> SourceContract:
        known = set(self.schema_spec.columns)
        for column in self.expectations.monotonic_columns:
            if column not in known:
                raise ValueError(f"{self.source_id}: monotonic column {column!r} not in schema")
        return self

    @model_validator(mode="after")
    def _covers_grain_is_delivered(self) -> SourceContract:
        unknown = set(self.covers.grain) - set(self.schema_spec.columns)
        if unknown:
            raise ValueError(f"{self.source_id}: covers.grain not delivered: {sorted(unknown)}")
        return self
