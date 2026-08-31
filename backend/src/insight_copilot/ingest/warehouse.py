"""The DuckDB warehouse: three real schemas plus a metadata schema.

WHY real schemas rather than name prefixes: the KPI contracts already declare
``source_view: gold.fct_revenue_daily``, and the compiler emits that identifier
verbatim. Making ``gold`` an actual schema means the contract's own text is the
executable path to the data, with no translation layer that could disagree with it.

The layer guarantees, from DataLayer section 11:

* **bronze** — raw rows exactly as delivered, plus batch provenance. Append-only.
  Never edited, never deleted from. A restatement adds rows; it does not overwrite.
* **silver** — conformed: one row per business key per period, timezone and units
  normalised, deduplicated, PII masked, with provenance back to bronze.
* **gold** — contract-grain marts, the dimensional cube and the driver panel.
* **meta** — batch registry, watermarks, quarantine, DQ results, drift, freshness.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

import duckdb
import pandas as pd

from insight_copilot.errors import IngestionError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

SCHEMAS = ("bronze", "silver", "gold", "meta")
BRONZE_COLUMNS = (
    "_batch_id",
    "_received_at",
    "_sim_time",
    "_source_file",
    "_row_hash",
    "_schema_version",
    "_period",
)
"""Provenance stamped on every bronze row. Leading underscores keep them out of the
delivered namespace, so a source that one day ships a column called ``period`` cannot
collide with the pipeline's own bookkeeping."""


class Warehouse:
    """A DuckDB connection with the layer schemas created and typed helpers."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = duckdb.connect(self._path)
        for schema in SCHEMAS:
            self._connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # ------------------------------------------------------------- lifecycle --
    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """The live connection. The query executor takes this, nothing else does."""
        return self._connection

    def close(self) -> None:
        """Release the file handle."""
        self._connection.close()

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ read --
    def query(self, sql: str, parameters: dict[str, Any] | None = None) -> pd.DataFrame:
        """Run a statement and return a frame. Errors are typed, never bare."""
        try:
            result = self._connection.execute(sql, parameters or {})
            return pd.DataFrame(result.fetchdf())
        except duckdb.Error as exc:
            raise IngestionError("warehouse query failed", detail=f"{exc}\n{sql}") from exc

    def execute(self, sql: str, parameters: dict[str, Any] | None = None) -> None:
        """Run a statement for its effect."""
        try:
            self._connection.execute(sql, parameters or {})
        except duckdb.Error as exc:
            raise IngestionError("warehouse statement failed", detail=f"{exc}\n{sql}") from exc

    def exists(self, schema: str, table: str) -> bool:
        """Does this table exist yet? Cheaper than catching a missing-table error."""
        found = self.query(
            "SELECT count(*) AS n FROM information_schema.tables "
            "WHERE table_schema = $schema AND table_name = $table",
            {"schema": schema, "table": table},
        )
        return int(found["n"].iloc[0]) > 0

    def row_count(self, schema: str, table: str) -> int:
        """Rows in a table, or zero if it does not exist."""
        if not self.exists(schema, table):
            return 0
        return int(self.query(f"SELECT count(*) AS n FROM {schema}.{table}")["n"].iloc[0])

    # ----------------------------------------------------------------- write --
    def append(self, schema: str, table: str, frame: pd.DataFrame) -> int:
        """Append a frame, creating the table on first use. Returns rows written."""
        if frame.empty and not self.exists(schema, table):
            self.replace(schema, table, frame)
            return 0
        if frame.empty:
            return 0
        self._connection.register("_incoming", frame)
        try:
            if self.exists(schema, table):
                columns = ", ".join(f'"{name}"' for name in self.columns(schema, table))
                self.execute(f"INSERT INTO {schema}.{table} SELECT {columns} FROM _incoming")
            else:
                self.execute(f"CREATE TABLE {schema}.{table} AS SELECT * FROM _incoming")
        finally:
            self._connection.unregister("_incoming")
        return len(frame)

    def replace(self, schema: str, table: str, frame: pd.DataFrame) -> int:
        """Replace a table wholesale. Used for silver and gold rebuilds only."""
        self._connection.register("_incoming", frame)
        try:
            self.execute(f"CREATE OR REPLACE TABLE {schema}.{table} AS SELECT * FROM _incoming")
        finally:
            self._connection.unregister("_incoming")
        return len(frame)

    def delete_where(
        self, schema: str, table: str, predicate: str, parameters: dict[str, Any]
    ) -> int:
        """Delete matching rows from a *rebuildable* table. Never used on bronze."""
        if not self.exists(schema, table):
            return 0
        before = self.row_count(schema, table)
        self.execute(f"DELETE FROM {schema}.{table} WHERE {predicate}", parameters)
        return before - self.row_count(schema, table)

    def columns(self, schema: str, table: str) -> list[str]:
        """Column names in declaration order."""
        found = self.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = $schema AND table_name = $table ORDER BY ordinal_position",
            {"schema": schema, "table": table},
        )
        return [str(name) for name in found["column_name"]]

    def drop_all(self) -> None:
        """Empty every schema. The reset half of the demo controls."""
        for schema in SCHEMAS:
            self.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            self.execute(f"CREATE SCHEMA {schema}")
        logger.info("warehouse.reset", path=self._path)
