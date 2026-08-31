"""The typed request and result of a contract compilation.

A caller — scheduled scan, persona narrative, or an analyst's question — describes
what it wants in these terms. It never writes SQL. That is the whole mechanism: an
LLM can propose a ``QueryRequest`` and still be structurally unable to reach data it
is not entitled to, because the request names *contract concepts*, and every one of
them is checked against the contract's own allowlist before a single character of
SQL is produced.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FilterOp = Literal["eq", "ne", "in", "between", "gte", "lte"]

FilterValue = str | int | float | dt.date
"""Filter values are data. They are bound as parameters and never rendered into SQL."""

MASK_SENTINEL = "MASKED"
"""What a masked column returns instead of a value.

WHY a sentinel rather than NULL or an omitted column: the narrator must be able to
say "margin detail is masked for your role" rather than "margin is unknown". A NULL
is indistinguishable from missing data; MASKED is a policy statement.
"""


class FilterClause(BaseModel):
    """One predicate on one contract dimension."""

    model_config = ConfigDict(frozen=True)

    dimension: str
    op: FilterOp = "eq"
    values: list[FilterValue] = Field(min_length=1)


class QueryRequest(BaseModel):
    """What a caller wants from one contract."""

    model_config = ConfigDict(frozen=True)

    contract_id: str
    grain: list[str] = Field(
        default_factory=list, description="Dimensions to group by. Empty = grand total."
    )
    measures: list[str] = Field(
        default_factory=list,
        description="Measure ids. Empty = the contract's primary measure only.",
    )
    filters: list[FilterClause] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=1_000_000)


class CompiledQuery(BaseModel):
    """Parameterised SQL plus everything the audit trail needs to replay it."""

    model_config = ConfigDict(frozen=True)

    contract_id: str
    contract_version: str
    role: str
    sql: str
    parameters: dict[str, FilterValue]
    sql_hash: str
    grain: list[str]
    measures: list[str]
    masked_columns: list[str]
    row_filter: str | None = None
    national_headline: Literal["full", "summary_only"] = "full"
