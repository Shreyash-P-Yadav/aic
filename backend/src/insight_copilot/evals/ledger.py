"""The truth ledger as typed rows.

``DataFrame.itertuples`` yields a dynamically generated class, so every field access on
it is untyped and a renamed ledger column would fail at runtime rather than at the type
check. Parsing each row into a model once puts the boundary where the project's rules
say it belongs — a pydantic model at every module boundary — and turns a column rename
into an immediate, named error.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pandas as pd
from pydantic import Field

from insight_copilot.contracts.common import StrictModel
from insight_copilot.errors import StatisticalError


class LedgerEvent(StrictModel):
    """One planted event, with only the fields the backtest is allowed to see.

    Deliberately narrow. ``true_contribution_inr`` and the scoped deltas are answer-key
    fields; the backtest reads the window and the grading keys, and nothing that would
    let it shortcut a measurement.
    """

    event_id: str
    type: str
    detectability: str
    data_condition: str
    window_start: dt.date
    window_end: dt.date
    measure_end: dt.date
    true_top_region: str
    excluded_from_calibration_fit: bool = Field(default=False)


def iter_events(ledger: pd.DataFrame) -> Iterator[LedgerEvent]:
    """Every ledger row as a typed event, in ledger order."""
    required = set(LedgerEvent.model_fields)
    missing = required - set(ledger.columns)
    if missing:
        raise StatisticalError(
            "the ledger is missing columns the backtest needs",
            detail=", ".join(sorted(missing)),
        )
    dates = [name for name in required if name.endswith(("_start", "_end"))]
    frame = ledger[sorted(required)].copy()
    for name in dates:
        frame[name] = pd.to_datetime(frame[name]).dt.date
    for row in frame.to_dict(orient="records"):
        yield LedgerEvent.model_validate({str(key): value for key, value in row.items()})
