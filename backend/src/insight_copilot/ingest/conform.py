"""The silver transforms: pure frame-in, frame-out functions with no I/O.

Everything the conform step does to a batch lives here so it can be tested against a
five-row fixture. The orchestration — which periods to rebuild, which batches win, how
to write the result — is :mod:`insight_copilot.ingest.silver`'s job.

The transforms, in the order silver applies them:

1. **Supersede and deduplicate.** Newest batch wins a period for a restating source;
   identical rows collapse by ``row_hash``; a repeated business key inside one batch
   resolves to the last line, because a file that lists a key twice means the later
   line corrects the earlier one.
2. **Timezone.** Every timestamp converted from the source's declared ``timestamp_tz``
   to IST, then *verified* against the business key where the key encodes a date.
3. **Currency.** Foreign-desk rows converted at the published policy rate-date.
4. **Conformed dimensions.** A canonical ``date``, an ``iso_week``, and ``region``
   derived from ``warehouse`` where the source is warehouse-grained.
5. **PII.** Declared-PII columns masked before anything is written or indexed.
"""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.harness.periods import week_label
from insight_copilot.ingest.masking import mask_column
from insight_copilot.ingest.policies import CurrencyPolicy

HOUSE_TIMEZONE = "Asia/Kolkata"
"""Every silver timestamp is IST. The business runs on IST; so does the warehouse."""

KEY_DATE = re.compile(r"^[A-Z]{3}-(\d{8})-")
"""Business keys of the form ``TIC-20260316-N001`` carry the date they were raised on.
That embedded date is what verifies a timezone declaration rather than assuming it."""

WAREHOUSE_REGION = re.compile(r"^DC-(?P<region>[A-Za-z]+)$")
"""Warehouse ids encode their home region. This is the conformed-dimension rule that
turns a warehouse-grained feed into something a region-grained KPI can join to."""


def resolve_versions(frame: pd.DataFrame, contract: SourceContract) -> pd.DataFrame:
    """Supersede-by-batch, then row-hash dedup, then last-line-wins on the key.

    Returns the surviving rows. The count difference against the input is what the
    ingest result reports as ``rows_deduplicated``.
    """
    if frame.empty:
        return frame
    working = frame.sort_values(["_period", "_received_at", "_batch_id"], kind="stable")
    if contract.restatement.policy == "supersede_by_batch":
        winners = working.groupby("_period", observed=True)["_batch_id"].transform("last")
        working = working.loc[working["_batch_id"] == winners]
    working = working.drop_duplicates(subset=["_period", "_row_hash"], keep="first")
    key = [column for column in contract.schema_spec.primary_key if column in working.columns]
    if key:
        working = working.drop_duplicates(subset=["_period", *key], keep="last")
    return working.reset_index(drop=True)


def normalise_timezone(frame: pd.DataFrame, contract: SourceContract) -> pd.DataFrame:
    """Convert every declared timestamp column from the source's zone to IST."""
    if frame.empty or contract.timestamp_tz == HOUSE_TIMEZONE:
        return frame
    result = frame.copy()
    for name, spec in contract.schema_spec.columns.items():
        if spec.type != "timestamp" or name not in result.columns:
            continue
        stamps = pd.to_datetime(result[name], errors="coerce")
        localised = stamps.dt.tz_localize(contract.timestamp_tz, ambiguous="NaT", nonexistent="NaT")
        result[name] = localised.dt.tz_convert(HOUSE_TIMEZONE).dt.tz_localize(None)
    return result


def key_date_mismatch(frame: pd.DataFrame, contract: SourceContract) -> pd.Series:
    """Rows whose timestamp lands on a different day from the one their key encodes.

    A conformance check, not a transform: after conversion this must be ~zero, and a
    non-zero rate means the declared ``timestamp_tz`` is wrong. It is the independent
    verification that keeps the declaration from being an unchecked assertion.
    """
    if frame.empty:
        return pd.Series(dtype=bool)
    keys = [name for name in contract.schema_spec.primary_key if name in frame.columns]
    stamp_column = contract.watermark
    if not keys or stamp_column not in frame.columns:
        return pd.Series(False, index=frame.index)
    encoded = frame[keys[0]].astype("string").str.extract(KEY_DATE, expand=False)
    if encoded.isna().all():
        return pd.Series(False, index=frame.index)
    stamped = pd.to_datetime(frame[stamp_column], errors="coerce").dt.strftime("%Y%m%d")
    return (encoded.notna() & (encoded != stamped)).fillna(False)


def convert_currency(
    frame: pd.DataFrame, contract: SourceContract, policy: CurrencyPolicy
) -> tuple[pd.DataFrame, int]:
    """Apply the published rate to rows from a declared foreign-booking unit.

    Only rows that both match the unit's dimensions *and* fall below its plausibility
    floor are converted: the desk books only its export lines in USD, so converting
    everything it sells would multiply genuine INR rows by eighty-three.
    """
    units = policy.units_for(contract.source_id)
    if frame.empty or not units:
        return frame, 0
    result = frame.copy()
    converted = 0
    for unit in units:
        selected = pd.Series(True, index=result.index)
        for column, value in unit.where.items():
            if column not in result.columns:
                selected = pd.Series(False, index=result.index)
                break
            selected &= result[column].astype("string") == value
        measures = [name for name in unit.measures if name in result.columns]
        if not selected.any() or not measures:
            continue
        anchor = pd.to_numeric(result[measures[0]], errors="coerce")
        selected &= (anchor > 0) & (anchor < unit.plausibility_floor_inr)
        if not selected.any():
            continue
        rate = policy.rate(unit.currency)
        for measure in measures:
            result.loc[selected, measure] = (
                pd.to_numeric(result.loc[selected, measure], errors="coerce") * rate
            ).round(4)
        converted += int(selected.sum())
    return result, converted


def add_conformed_dimensions(frame: pd.DataFrame, contract: SourceContract) -> pd.DataFrame:
    """Add the canonical ``date``, ``iso_week`` and warehouse-derived ``region``."""
    if frame.empty:
        return frame
    result = frame.copy()
    result["date"] = _business_date(result, contract)
    if "iso_week" not in result.columns:
        result["iso_week"] = result["date"].map(lambda day: "" if pd.isna(day) else week_label(day))
    if "warehouse" in result.columns and "region" not in result.columns:
        result["region"] = (
            result["warehouse"]
            .astype("string")
            .str.extract(WAREHOUSE_REGION, expand=False)
            .fillna("UNKNOWN")
        )
    return result


def mask_pii(frame: pd.DataFrame, contract: SourceContract) -> pd.DataFrame:
    """Mask every column the contract declares as PII. Runs before anything is written."""
    columns = [name for name in contract.schema_spec.pii_columns if name in frame.columns]
    if frame.empty or not columns:
        return frame
    result = frame.copy()
    for name in columns:
        result[name] = mask_column(result[name], name)
    return result


def _business_date(frame: pd.DataFrame, contract: SourceContract) -> pd.Series:
    """The calendar day a row belongs to, whatever the source calls its date column."""
    if contract.covers.period == "previous_iso_week" and "iso_week" in frame.columns:
        return frame["iso_week"].astype("string").map(_week_monday)
    column = contract.watermark
    if column not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index)
    return pd.to_datetime(frame[column], errors="coerce").dt.date


def _week_monday(label: object) -> dt.date | None:
    """Monday of an ISO-week label, or ``None`` when the label is unusable."""
    text = str(label)
    if "-W" not in text:
        return None
    year, _, week = text.partition("-W")
    try:
        return dt.date.fromisocalendar(int(year), int(week), 1)
    except ValueError:
        return None
