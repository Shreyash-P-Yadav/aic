"""Silver — one conformed row per business key per period, with provenance to bronze.

Silver is *rebuilt*, never patched. When a batch lands, the periods it touches are
recomputed from every bronze row that has ever claimed them and the result replaces
the silver rows for exactly those periods. That is what makes a late batch cheap: a
Tuesday arriving three days late rebuilds Tuesday, not the quarter.

Rebuilding also makes supersession trivially correct. There is no "apply the delta"
step that could drift from the bronze history; the newest batch simply wins the
period on the next rebuild, and the version it replaced is still in bronze, still
queryable, exactly as the audit trail requires.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.ingest.conform import (
    add_conformed_dimensions,
    convert_currency,
    key_date_mismatch,
    mask_pii,
    normalise_timezone,
    resolve_versions,
)
from insight_copilot.ingest.dq_store import DQStore
from insight_copilot.ingest.policies import CurrencyPolicy, load_currency_policy
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

PROVENANCE = ("_batch_id", "_row_hash", "_period", "_received_at", "_sim_time")
"""Bronze bookkeeping carried through to silver, so every conformed row is traceable
back to the file it arrived in. ``_source_file`` and ``_schema_version`` stay in
bronze: they describe the delivery, not the row."""


@dataclass
class SilverRebuild:
    """What one period rebuild did."""

    source_id: str
    periods: list[str]
    rows_in: int = 0
    rows_out: int = 0
    rows_deduplicated: int = 0
    rows_quarantined: int = 0
    currency_converted: int = 0
    key_date_mismatches: int = 0
    columns_dropped: list[str] = field(default_factory=list)


class SilverConformer:
    """Rebuilds ``silver.<source_id>`` for a set of periods."""

    def __init__(
        self,
        warehouse: Warehouse,
        registry: ContractRegistry,
        dq_store: DQStore,
        policy: CurrencyPolicy | None = None,
    ) -> None:
        self._warehouse = warehouse
        self._registry = registry
        self._dq = dq_store
        self._policy = policy or load_currency_policy()

    def rebuild(self, source_id: str, periods: list[str]) -> SilverRebuild:
        """Recompute silver for exactly these periods, from bronze."""
        contract = self._registry.source(source_id)
        result = SilverRebuild(source_id=source_id, periods=sorted(periods))
        raw = self._bronze_rows(source_id, periods)
        result.rows_in = len(raw)
        if raw.empty:
            self._write(contract, periods, raw)
            return result

        kept, dropped = _keep_declared_columns(raw, contract)
        result.columns_dropped = dropped

        resolved = resolve_versions(kept, contract)
        result.rows_deduplicated = len(kept) - len(resolved)

        held = self._dq.quarantined_hashes(source_id, sorted(set(resolved["_batch_id"])))
        if held:
            before = len(resolved)
            resolved = resolved.loc[~resolved["_row_hash"].isin(held)].reset_index(drop=True)
            result.rows_quarantined = before - len(resolved)

        conformed = normalise_timezone(resolved, contract)
        result.key_date_mismatches = int(key_date_mismatch(conformed, contract).sum())
        conformed, converted = convert_currency(conformed, contract, self._policy)
        result.currency_converted = converted
        conformed = add_conformed_dimensions(conformed, contract)
        conformed = mask_pii(conformed, contract)

        result.rows_out = len(conformed)
        self._write(contract, periods, conformed)
        logger.info(
            "silver.rebuilt",
            source_id=source_id,
            periods=len(periods),
            rows_in=result.rows_in,
            rows_out=result.rows_out,
            deduplicated=result.rows_deduplicated,
            quarantined=result.rows_quarantined,
            converted=result.currency_converted,
        )
        return result

    # ------------------------------------------------------------------ read --
    def _bronze_rows(self, source_id: str, periods: list[str]) -> pd.DataFrame:
        """Every bronze row that has ever claimed one of these periods.

        Period labels sort lexicographically in calendar order — that is why they are
        ``2026-03-08`` and ``2026-W11`` rather than anything friendlier — so a range
        bound alongside the exact membership test lets DuckDB skip most of a
        thirty-six-month bronze table instead of scanning it on every daily rebuild.
        """
        if not self._warehouse.exists("bronze", source_id) or not periods:
            return pd.DataFrame()
        return self._warehouse.query(
            f"SELECT * FROM bronze.{source_id} "
            "WHERE _period BETWEEN $lo AND $hi AND list_contains($periods, _period)",
            {"periods": list(periods), "lo": min(periods), "hi": max(periods)},
        )

    def _write(self, contract: SourceContract, periods: list[str], frame: pd.DataFrame) -> None:
        """Replace the silver rows for these periods with the rebuilt ones."""
        table = contract.source_id
        if self._warehouse.exists("silver", table):
            self._warehouse.delete_where(
                "silver",
                table,
                "_period BETWEEN $lo AND $hi AND list_contains($periods, _period)",
                {"periods": list(periods), "lo": min(periods), "hi": max(periods)},
            )
            if not frame.empty:
                self._align(table, frame)
                self._warehouse.append("silver", table, frame)
            return
        self._warehouse.replace("silver", table, frame)

    def _align(self, table: str, frame: pd.DataFrame) -> None:
        """Widen the silver table for a column a later batch introduced."""
        existing = set(self._warehouse.columns("silver", table))
        for column in frame.columns:
            if column not in existing:
                self._warehouse.execute(f'ALTER TABLE silver.{table} ADD COLUMN "{column}" VARCHAR')
        for column in existing - set(frame.columns):
            frame[column] = None

    # ------------------------------------------------------------------ query --
    def table(self, source_id: str) -> pd.DataFrame:
        """The whole conformed table for a source. Tests and gold read this."""
        if not self._warehouse.exists("silver", source_id):
            return pd.DataFrame()
        return self._warehouse.query(f"SELECT * FROM silver.{source_id}")


def _keep_declared_columns(
    frame: pd.DataFrame, contract: SourceContract
) -> tuple[pd.DataFrame, list[str]]:
    """Drop columns the contract does not declare, and say which were dropped.

    This is the second half of ``drift_policy: quarantine_and_alert``: the alert was
    raised at bronze, and the undeclared column is quarantined *out of silver* here.
    The values are not lost — bronze keeps every column exactly as delivered — but
    nothing undeclared can reach a mart, so a renamed field cannot silently become a
    new measure.
    """
    declared = set(contract.schema_spec.columns) | set(PROVENANCE)
    dropped = sorted(column for column in frame.columns if column not in declared)
    keep = [column for column in frame.columns if column in declared]
    return frame[keep].copy(), dropped
