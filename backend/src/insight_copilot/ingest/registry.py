"""The batch registry and the watermark table — where idempotency actually lives.

Two rules from DataLayer section 10.5, implemented here and nowhere else:

* **Idempotency by ``(source_id, batch_id)``.** A batch already recorded is skipped
  outright. This is what makes a re-delivered file a no-op rather than a doubled
  number, and it is checked *before* the file is read, so a duplicate costs nothing.
* **Watermark per source, advanced only when a period is complete; a late batch for
  an older period rewinds the watermark for that period.** The rewind is per period,
  never global — recomputing thirty-six months because a Tuesday arrived late is the
  behaviour this design exists to avoid.

Supersede-by-batch also lives here: the registry knows which batch currently *wins*
each period, and prior versions stay recorded so the audit trail can show what we
believed and when.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from insight_copilot.harness.manifest import BatchManifest
from insight_copilot.ingest.models import BatchStatus, WatermarkState
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

BATCHES_DDL = """
CREATE TABLE IF NOT EXISTS meta.batches (
    source_id        VARCHAR NOT NULL,
    batch_id         VARCHAR NOT NULL,
    periods          VARCHAR NOT NULL,
    generated_at_sim TIMESTAMPTZ NOT NULL,
    received_at      TIMESTAMPTZ NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL,
    is_restatement   BOOLEAN NOT NULL,
    supersedes       VARCHAR NOT NULL,
    row_count        BIGINT NOT NULL,
    rows_landed      BIGINT NOT NULL,
    rows_quarantined BIGINT NOT NULL,
    checksum         VARCHAR NOT NULL,
    schema_version   INTEGER NOT NULL,
    status           VARCHAR NOT NULL,
    PRIMARY KEY (source_id, batch_id)
)
"""

WATERMARKS_DDL = """
CREATE TABLE IF NOT EXISTS meta.watermarks (
    source_id  VARCHAR NOT NULL,
    period     VARCHAR NOT NULL,
    batch_id   VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    revisions  INTEGER NOT NULL,
    PRIMARY KEY (source_id, period)
)
"""


class BatchRegistry:
    """Which batches exist, which one wins each period, and how far each source is."""

    def __init__(self, warehouse: Warehouse) -> None:
        self._warehouse = warehouse
        self.create_tables(warehouse)

    @staticmethod
    def create_tables(warehouse: Warehouse) -> None:
        """Create the registry tables if they are absent. Idempotent, and re-runnable
        after a reset drops the schemas."""
        warehouse.execute(BATCHES_DDL)
        warehouse.execute(WATERMARKS_DDL)

    # ------------------------------------------------------------ idempotency --
    def is_known(self, source_id: str, batch_id: str) -> bool:
        """Has this exact batch already been recorded? The first idempotency key."""
        found = self._warehouse.query(
            "SELECT count(*) AS n FROM meta.batches "
            "WHERE source_id = $source_id AND batch_id = $batch_id",
            {"source_id": source_id, "batch_id": batch_id},
        )
        return int(found["n"].iloc[0]) > 0

    def record(
        self,
        manifest: BatchManifest,
        *,
        status: BatchStatus,
        rows_landed: int,
        rows_quarantined: int,
        ingested_at: dt.datetime,
    ) -> None:
        """Write the batch's registry row. Called exactly once per accepted batch."""
        self._warehouse.execute(
            "INSERT INTO meta.batches VALUES ($source_id, $batch_id, $periods, "
            "$generated_at_sim, $received_at, $ingested_at, $is_restatement, $supersedes, "
            "$row_count, $rows_landed, $rows_quarantined, $checksum, $schema_version, $status)",
            {
                "source_id": manifest.source_id,
                "batch_id": manifest.batch_id,
                "periods": json.dumps(manifest.covers.periods),
                "generated_at_sim": manifest.generated_at_sim,
                "received_at": manifest.received_at,
                "ingested_at": ingested_at,
                "is_restatement": manifest.is_restatement,
                "supersedes": json.dumps(manifest.supersedes),
                "row_count": manifest.row_count,
                "rows_landed": rows_landed,
                "rows_quarantined": rows_quarantined,
                "checksum": manifest.checksum,
                "schema_version": manifest.schema_version,
                "status": status,
            },
        )

    # -------------------------------------------------------------- watermark --
    def advance(
        self, source_id: str, periods: list[str], batch_id: str, now: dt.datetime
    ) -> list[WatermarkState]:
        """Close (or re-open) each period this batch covers.

        Returns one state per period, with ``rewound`` set where a period that had
        already been closed is being re-opened. That flag is what tells the pipeline
        trigger to recompute *this window only*.
        """
        existing = self._warehouse.query(
            "SELECT period, revisions FROM meta.watermarks WHERE source_id = $source_id",
            {"source_id": source_id},
        )
        revisions = {str(row.period): int(str(row.revisions)) for row in existing.itertuples()}
        states: list[WatermarkState] = []
        for period in periods:
            was_known = period in revisions
            revision = revisions.get(period, -1) + 1
            self._warehouse.execute(
                "INSERT OR REPLACE INTO meta.watermarks VALUES "
                "($source_id, $period, $batch_id, $updated_at, $revisions)",
                {
                    "source_id": source_id,
                    "period": period,
                    "batch_id": batch_id,
                    "updated_at": now,
                    "revisions": revision,
                },
            )
            states.append(
                WatermarkState(
                    source_id=source_id,
                    period=period,
                    batch_id=batch_id,
                    updated_at=now,
                    rewound=was_known,
                )
            )
        if any(state.rewound for state in states):
            logger.info(
                "watermark.rewound",
                source_id=source_id,
                periods=[state.period for state in states if state.rewound],
                batch_id=batch_id,
            )
        return states

    def high_watermark(self, source_id: str) -> str | None:
        """The newest period this source has ever closed."""
        found = self._warehouse.query(
            "SELECT max(period) AS period FROM meta.watermarks WHERE source_id = $source_id",
            {"source_id": source_id},
        )
        value = found["period"].iloc[0] if len(found) else None
        return None if value is None or pd.isna(value) else str(value)

    def winning_batches(self, source_id: str, periods: list[str]) -> dict[str, str]:
        """The batch that currently owns each period, under supersede-by-batch."""
        if not periods:
            return {}
        # Filtered in pandas rather than with an interpolated IN list: no value this
        # pipeline handles is ever pasted into SQL text, period labels included.
        found = self._warehouse.query(
            "SELECT period, batch_id FROM meta.watermarks WHERE source_id = $source_id",
            {"source_id": source_id},
        )
        wanted = set(periods)
        return {
            str(row.period): str(row.batch_id)
            for row in found.itertuples()
            if str(row.period) in wanted
        }

    # ------------------------------------------------------------------ read --
    def latest_batch(self, source_id: str) -> pd.Series | None:
        """The most recently received *accepted* batch for a source, or ``None``."""
        found = self._warehouse.query(
            "SELECT * FROM meta.batches WHERE source_id = $source_id "
            "AND status IN ('ingested', 'quarantined', 'empty') "
            "ORDER BY received_at DESC, batch_id DESC LIMIT 1",
            {"source_id": source_id},
        )
        return None if found.empty else found.iloc[0]

    def batches(self, source_id: str | None = None) -> pd.DataFrame:
        """The whole registry, or one source's slice, newest first."""
        if source_id is None:
            return self._warehouse.query(
                "SELECT * FROM meta.batches ORDER BY received_at DESC, batch_id DESC"
            )
        return self._warehouse.query(
            "SELECT * FROM meta.batches WHERE source_id = $source_id "
            "ORDER BY received_at DESC, batch_id DESC",
            {"source_id": source_id},
        )

    def revisions_of(self, source_id: str, period: str) -> int:
        """How many times a period has been superseded. Zero on first delivery."""
        found = self._warehouse.query(
            "SELECT revisions FROM meta.watermarks "
            "WHERE source_id = $source_id AND period = $period",
            {"source_id": source_id, "period": period},
        )
        return 0 if found.empty else int(found["revisions"].iloc[0])
