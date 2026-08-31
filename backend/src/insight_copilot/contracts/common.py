"""Primitives shared by the KPI and source contract models.

WHY a separate module: both contract families need the same strict-model base, the
same identifier allowlist regex, and the same defence-in-depth check on
contract-authored SQL fragments. Duplicating them would let the two drift apart,
and the compiler's safety depends on exactly one definition of "valid identifier".
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

Calendar = Literal["fiscal_apr_mar", "iso_week", "gregorian"]
Unit = Literal["INR", "percent", "ratio", "units"]
Aggregation = Literal["sum", "weighted", "average"]
QualityTier = Literal["high", "medium", "medium_low", "low"]
DriverDirection = Literal["positive", "negative", "contextual"]

SQL_FRAGMENT_FORBIDDEN = re.compile(r";|--|/\*|\*/")
"""Contract-authored SQL is trusted input, but a stray statement separator in a
hand-edited YAML would let one contract's fragment terminate another's query. This
is a defence-in-depth check at load time, not the primary injection control — the
primary control is that user *values* never reach the SQL string at all."""

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
"""Every column, dimension and view name is a lowercase snake_case identifier.
The compiler's allowlist is only as safe as the tokens it admits."""


class StrictModel(BaseModel):
    """Base for every contract model: unknown keys are an error, not a shrug.

    WHY ``extra='forbid'``: a typo in a YAML key (``materiallity:``) would otherwise
    load silently and the engine would run on defaults, producing plausible numbers
    from the wrong governance. Better to fail at ``make validate-contracts``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
