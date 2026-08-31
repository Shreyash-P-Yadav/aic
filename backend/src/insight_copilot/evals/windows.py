"""Window-level helpers the backtest uses: rung 1 over one window, and the masks.

Separated from the runner so the runner reads as the sequence it is — fit, scan,
replay, compare — rather than as that sequence interleaved with cube arithmetic.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from insight_copilot.engine.attribute_where import Attributor, WhereResult
from insight_copilot.engine.cube import CubeWindow, national_factor, segment_actual_forecast
from insight_copilot.engine.series import Series
from insight_copilot.errors import StatisticalError
from insight_copilot.evals.ledger import LedgerEvent, iter_events
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


def attribute_window(
    series: Series,
    expected: np.ndarray,
    cube: pd.DataFrame,
    attributor: Attributor,
    start: dt.date,
    end: dt.date,
) -> WhereResult | None:
    """Rung 1 over one event window, against a four-week pre-window baseline."""
    window = CubeWindow.ending_before(start, end)
    mask = series.mask_between(start, end)
    baseline_mask = series.mask_between(window.baseline_start, window.baseline_end)
    if not mask.any() or not baseline_mask.any():
        return None
    factor = national_factor(
        float(expected[mask].sum()), float(series.values[baseline_mask].sum()), window
    )
    frame = segment_actual_forecast(
        cube[
            (cube["date"] >= pd.Timestamp(window.baseline_start))
            & (cube["date"] <= pd.Timestamp(window.test_end))
        ],
        window,
        dimensions=["region", "channel", "category"],
        measure="net_revenue_inr",
        national_factor=factor,
    )
    if frame.empty:
        return None
    try:
        return attributor.attribute(
            frame,
            ["region", "channel", "category"],
            actual_column="actual",
            forecast_column="forecast",
        )
    except StatisticalError as exc:
        logger.warning("backtest.attribution_failed", start=str(start), error=str(exc))
        return None


def query_for(row: LedgerEvent) -> str:
    """The retrieval query the engine would form from what it can see.

    Built from the *detected* shape of the movement — its type family and the region
    the attribution named — never from the ledger's mechanism field, which the engine
    does not have.
    """
    kind = str(row.type).replace("_", " ")
    region = str(row.true_top_region)
    return f"{kind} {region} region revenue shortfall demand supply price"


def event_windows(ledger: pd.DataFrame) -> list[tuple[dt.date, dt.date]]:
    """Every ledger window, as dates. Held out of both the fit and the calibration."""
    return [(event.window_start, event.measure_end) for event in iter_events(ledger)]


def mask_for(series: Series, windows: list[tuple[dt.date, dt.date]]) -> np.ndarray:
    """Boolean mask of every day touched by any event."""
    mask = np.zeros(len(series), dtype=bool)
    for start, end in windows:
        mask |= series.mask_between(start, end)
    return mask
