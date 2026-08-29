"""Where data-quality findings are kept, so they can be read back and counted.

Split from the gate itself because the gate is a pure evaluation of a contract
against a frame — testable without a database — while this is the persistence half.
Every table here is a demo artefact: the admin panel renders the quarantine counts,
the evidence drawer renders the DQ results, and the ``c4`` data-trust signal reads
both.
"""

from __future__ import annotations

import json

import pandas as pd

from insight_copilot.ingest.models import DQResult, DriftAlert, QuarantineRecord
from insight_copilot.ingest.warehouse import Warehouse

QUARANTINE_DDL = """
CREATE TABLE IF NOT EXISTS meta.quarantine_rows (
    source_id VARCHAR NOT NULL,
    batch_id  VARCHAR NOT NULL,
    row_hash  VARCHAR NOT NULL,
    rule      VARCHAR NOT NULL,
    reason    VARCHAR NOT NULL
)
"""

DQ_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS meta.dq_results (
    source_id     VARCHAR NOT NULL,
    batch_id      VARCHAR NOT NULL,
    expectation   VARCHAR NOT NULL,
    outcome       VARCHAR NOT NULL,
    observed      DOUBLE,
    threshold     DOUBLE,
    rows_affected BIGINT NOT NULL,
    detail        VARCHAR NOT NULL
)
"""

DRIFT_DDL = """
CREATE TABLE IF NOT EXISTS meta.drift_alerts (
    source_id VARCHAR NOT NULL,
    batch_id  VARCHAR NOT NULL,
    kind      VARCHAR NOT NULL,
    columns   VARCHAR NOT NULL,
    policy    VARCHAR NOT NULL,
    detail    VARCHAR NOT NULL
)
"""


class DQStore:
    """Persistence for quarantine rows, expectation results and drift alerts."""

    def __init__(self, warehouse: Warehouse) -> None:
        self._warehouse = warehouse
        self.create_tables(warehouse)

    @staticmethod
    def create_tables(warehouse: Warehouse) -> None:
        """Create the DQ tables if they are absent. Re-runnable after a reset."""
        for statement in (QUARANTINE_DDL, DQ_RESULTS_DDL, DRIFT_DDL):
            warehouse.execute(statement)

    def persist(
        self,
        results: list[DQResult],
        quarantine: list[QuarantineRecord],
        drift: list[DriftAlert],
    ) -> None:
        """Record findings so the admin panel and ``c4`` can read them back."""
        if results:
            self._warehouse.append("meta", "dq_results", _results_frame(results))
        rows = _quarantine_frame(quarantine)
        if not rows.empty:
            self._warehouse.append("meta", "quarantine_rows", rows)
        if drift:
            self._warehouse.append("meta", "drift_alerts", _drift_frame(drift))

    def quarantined_hashes(self, source_id: str, batch_ids: list[str]) -> set[str]:
        """Row hashes held back for these batches — the anti-join silver applies."""
        if not batch_ids:
            return set()
        held = self._warehouse.query(
            "SELECT batch_id, row_hash FROM meta.quarantine_rows WHERE source_id = $source_id",
            {"source_id": source_id},
        )
        wanted = set(batch_ids)
        return {str(row.row_hash) for row in held.itertuples() if str(row.batch_id) in wanted}

    def quarantine_counts(self) -> pd.DataFrame:
        """Rows held back per source and rule — the DQ dashboard's table."""
        return self._warehouse.query(
            "SELECT source_id, rule, count(*) AS rows_quarantined "
            "FROM meta.quarantine_rows GROUP BY source_id, rule ORDER BY 3 DESC"
        )

    def results(self, source_id: str | None = None) -> pd.DataFrame:
        """Every expectation result, or one source's."""
        if source_id is None:
            return self._warehouse.query("SELECT * FROM meta.dq_results")
        return self._warehouse.query(
            "SELECT * FROM meta.dq_results WHERE source_id = $source_id",
            {"source_id": source_id},
        )

    def drift_alerts(self, source_id: str | None = None) -> pd.DataFrame:
        """Every schema-drift alert raised, or one source's."""
        if source_id is None:
            return self._warehouse.query("SELECT * FROM meta.drift_alerts")
        return self._warehouse.query(
            "SELECT * FROM meta.drift_alerts WHERE source_id = $source_id",
            {"source_id": source_id},
        )


def _results_frame(results: list[DQResult]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_id": result.source_id,
                "batch_id": result.batch_id,
                "expectation": result.expectation,
                "outcome": result.outcome,
                "observed": result.observed,
                "threshold": result.threshold,
                "rows_affected": result.rows_affected,
                "detail": result.detail,
            }
            for result in results
        ]
    )


def _quarantine_frame(quarantine: list[QuarantineRecord]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_id": record.source_id,
                "batch_id": record.batch_id,
                "row_hash": row_hash,
                "rule": record.rule,
                "reason": record.reason,
            }
            for record in quarantine
            for row_hash in record.row_hashes
        ],
        columns=["source_id", "batch_id", "row_hash", "rule", "reason"],
    )


def _drift_frame(drift: list[DriftAlert]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_id": alert.source_id,
                "batch_id": alert.batch_id,
                "kind": alert.kind,
                "columns": json.dumps(alert.columns),
                "policy": alert.policy,
                "detail": alert.detail,
            }
            for alert in drift
        ]
    )
