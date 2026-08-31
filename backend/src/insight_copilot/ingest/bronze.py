"""Bronze — raw rows exactly as delivered, plus the provenance to replay them.

Guarantees: immutable, append-only, replayable, never edited. A restatement *adds*
rows under a new batch id; the superseded version stays exactly where it was, which
is what lets the audit trail answer "what did we believe on Monday?".

The only transformation bronze performs is **type coercion against the contract's
declared types**, and only because four feeds land as CSV or JSON and therefore
arrive as text. Coercion failures do not raise: the value is kept as null and the row
is recorded as a type violation for the DQ layer to quarantine. Bronze never decides
what is wrong; it records what arrived.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.contracts.source_models import ColumnType, SourceContract
from insight_copilot.harness.manifest import BatchManifest
from insight_copilot.harness.periods import STATIC_PERIOD, day_label
from insight_copilot.ingest.models import DriftAlert
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

ROW_HASH_KEYS = ("insightcopilot01", "rowhashsecondary")
"""Two 16-byte pandas hash keys — the length pandas requires. Two independent
64-bit hashes concatenated give a 128-bit row digest. With ~10^7
rows the collision probability is ~10^-24, so a hash collision can never be mistaken
for a duplicate row — and unlike a per-row ``blake2b`` this stays vectorised, which
matters when the historical load hashes 1.3 million order lines in one batch."""


@dataclass(frozen=True)
class BronzeLoad:
    """What one batch put into bronze."""

    frame: pd.DataFrame
    rows: int
    drift: list[DriftAlert]
    coercion_failures: dict[str, int]


def row_hash(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    """A content digest per row over the *declared* columns only.

    Undeclared columns are excluded deliberately: a schema drift that adds an alias
    must not make otherwise-identical rows look new, or the drifted weeks would
    escape row-hash dedup entirely.
    """
    if frame.empty:
        return pd.Series(dtype="object")
    present = [column for column in columns if column in frame.columns]
    subset = frame[present]
    low, high = (
        pd.util.hash_pandas_object(subset, index=False, hash_key=key).to_numpy("uint64")
        for key in ROW_HASH_KEYS
    )
    return pd.Series(
        np.char.add(np.char.mod("%016x", high), np.char.mod("%016x", low)), index=frame.index
    )


class BronzeLoader:
    """Lands one batch into ``bronze.<source_id>``."""

    def __init__(self, warehouse: Warehouse) -> None:
        self._warehouse = warehouse

    def load(
        self,
        contract: SourceContract,
        frame: pd.DataFrame,
        manifest: BatchManifest,
        *,
        sim_time: dt.datetime,
        source_file: str,
    ) -> BronzeLoad:
        """Coerce, stamp and append. Returns the stamped frame for the DQ layer."""
        declared = list(contract.schema_spec.columns)
        drift = detect_drift(contract, frame, manifest.batch_id)
        typed, failures = _coerce(frame, contract)

        typed["_batch_id"] = manifest.batch_id
        typed["_received_at"] = manifest.received_at
        typed["_sim_time"] = sim_time
        typed["_source_file"] = source_file
        typed["_row_hash"] = row_hash(frame, declared)
        typed["_schema_version"] = manifest.schema_version
        typed["_period"] = _row_periods(typed, contract, manifest)

        table = contract.source_id
        self._align(table, typed)
        written = self._warehouse.append("bronze", table, typed)
        logger.info(
            "bronze.loaded",
            source_id=contract.source_id,
            batch_id=manifest.batch_id,
            rows=written,
            drift=len(drift),
        )
        return BronzeLoad(frame=typed, rows=written, drift=drift, coercion_failures=failures)

    def _align(self, table: str, frame: pd.DataFrame) -> None:
        """Add any column the existing bronze table lacks, so an append never fails.

        A drifted batch carrying a new column widens the table with nulls for every
        earlier row. That is the append-only way to record a shape change: nothing
        already written is touched.
        """
        if not self._warehouse.exists("bronze", table):
            return
        existing = set(self._warehouse.columns("bronze", table))
        for column in frame.columns:
            if column not in existing:
                self._warehouse.execute(f'ALTER TABLE bronze.{table} ADD COLUMN "{column}" VARCHAR')
        for column in existing - set(frame.columns):
            frame[column] = None


def detect_drift(contract: SourceContract, frame: pd.DataFrame, batch_id: str) -> list[DriftAlert]:
    """Compare the delivered shape against the contract's declared schema."""
    declared = set(contract.schema_spec.columns)
    delivered = set(frame.columns)
    policy = contract.schema_spec.drift_policy
    alerts: list[DriftAlert] = []
    unexpected = sorted(delivered - declared)
    missing = sorted(declared - delivered)
    if unexpected:
        alerts.append(
            DriftAlert(
                source_id=contract.source_id,
                batch_id=batch_id,
                kind="unexpected_column",
                columns=unexpected,
                policy=policy,
                detail=(
                    f"{contract.source_id} delivered {unexpected} which its schema "
                    f"v{contract.schema_spec.version} does not declare"
                ),
            )
        )
    if missing:
        alerts.append(
            DriftAlert(
                source_id=contract.source_id,
                batch_id=batch_id,
                kind="missing_column",
                columns=missing,
                policy=policy,
                detail=f"{contract.source_id} omitted declared columns {missing}",
            )
        )
    return alerts


def _coerce(frame: pd.DataFrame, contract: SourceContract) -> tuple[pd.DataFrame, dict[str, int]]:
    """Cast delivered columns to their declared types, counting what would not cast."""
    typed = frame.copy()
    failures: dict[str, int] = {}
    for name, spec in contract.schema_spec.columns.items():
        if name not in typed.columns:
            continue
        before = typed[name].notna().sum()
        typed[name] = _cast(typed[name], spec.type)
        lost = int(before - typed[name].notna().sum())
        if lost:
            failures[name] = lost
    return typed, failures


def _cast(values: pd.Series, column_type: ColumnType) -> pd.Series:
    """One column, coerced. Unparseable values become null and are counted, not raised.

    A column that already carries its declared type is returned untouched. Parquet
    delivers typed columns, and re-parsing 1.3 million timestamps through a
    mixed-format parser would make the historical load minutes slower for no change.
    """
    if _already_typed(values, column_type):
        return values
    if column_type in ("integer", "bigint"):
        return pd.to_numeric(values, errors="coerce").astype("Float64").astype("Int64")
    if column_type == "decimal":
        return pd.to_numeric(values, errors="coerce").astype("Float64")
    if column_type == "date":
        return pd.to_datetime(values, errors="coerce", format="mixed").dt.date
    if column_type == "timestamp":
        return pd.to_datetime(values, errors="coerce", format="mixed")
    if column_type == "boolean":
        return values.map(_to_bool).astype("boolean")
    return values.astype("string")


def _to_bool(value: object) -> bool | None:
    """CSV and JSON deliver booleans as text in four different spellings."""
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if text in ("true", "t", "1", "yes"):
        return True
    if text in ("false", "f", "0", "no"):
        return False
    return None


def _row_periods(
    frame: pd.DataFrame, contract: SourceContract, manifest: BatchManifest
) -> pd.Series[str] | str:
    """The period each *row* belongs to, not the period the batch is named after.

    A restating weekly batch covers three weeks in one file. Stamping every row with
    the batch's newest period would make "rebuild exactly the affected window"
    rebuild the wrong window, so the label is derived from each row's own watermark
    value and only falls back to the manifest when the source has no calendar
    position at all.
    """
    fallback = manifest.covers.periods[0] if manifest.covers.periods else STATIC_PERIOD
    if frame.empty or contract.covers.period == "static":
        return fallback
    column = contract.watermark
    if column not in frame.columns:
        return fallback
    if contract.covers.period == "previous_iso_week":
        return frame[column].astype("string").fillna(fallback)
    stamps = pd.to_datetime(frame[column], errors="coerce")
    labels = stamps.dt.date.map(lambda day: fallback if pd.isna(day) else day_label(day))
    return labels.astype("string")


def _already_typed(values: pd.Series, column_type: ColumnType) -> bool:
    """Is this column already the declared type? Then coercion is a no-op."""
    kind = values.dtype.kind
    if column_type in ("integer", "bigint"):
        return kind == "i" or isinstance(values.dtype, pd.Int64Dtype)
    if column_type == "decimal":
        return kind == "f" or isinstance(values.dtype, pd.Float64Dtype)
    if column_type == "timestamp":
        return kind == "M"
    if column_type == "boolean":
        return kind == "b" or isinstance(values.dtype, pd.BooleanDtype)
    if column_type == "date":
        # ``object`` holding ``datetime.date`` is what parquet gives back for a DATE
        # column; anything else has to go through the parser.
        return kind == "O" and isinstance(values.iloc[0] if len(values) else None, dt.date)
    return isinstance(values.dtype, pd.StringDtype)
