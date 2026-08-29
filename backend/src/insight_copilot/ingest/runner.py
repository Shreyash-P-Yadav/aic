"""``IngestionRunner`` — bronze, DQ, silver, gold, watermarks, and the landed event.

One batch in, one :class:`IngestResult` out. The order is fixed and each step is a
component that can be tested on its own:

1. **Idempotency.** A batch id already in the registry is skipped before the file is
   even read.
2. **Bronze.** Raw rows plus provenance, appended immutably. Drift is detected here.
3. **DQ.** Contract expectations evaluated; failing rows quarantined, never dropped.
4. **Silver.** The affected periods rebuilt from bronze, superseded and conformed.
5. **Gold.** The affected *days* rebuilt in every contract mart, the cube and the panel.
6. **Watermark.** Each period closed, or re-opened if a late batch rewound it.
7. **DataLandedEvent.** Emitted with the KPIs the source feeds — and only those.

Batches are processed in groups rather than one at a time. A ticket feed lands every
thirty minutes, so a day of catch-up is forty-eight batches over the same handful of
periods; rebuilding silver and gold once for the union of their windows is the
difference between a demo that keeps up with the clock and one that does not.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.harness.landing import LandedBatch
from insight_copilot.harness.periods import affected_days
from insight_copilot.ingest.bronze import BronzeLoader
from insight_copilot.ingest.dq import DataQualityGate
from insight_copilot.ingest.dq_store import DQStore
from insight_copilot.ingest.gold import GoldBuilder
from insight_copilot.ingest.models import (
    BatchStatus,
    DataLandedEvent,
    IngestResult,
    QuarantineRecord,
)
from insight_copilot.ingest.panel import PanelBuilder
from insight_copilot.ingest.registry import BatchRegistry
from insight_copilot.ingest.silver import SilverConformer
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


@dataclass
class _Pending:
    """Periods and days a group of batches left dirty, per source."""

    periods: set[str] = field(default_factory=set)
    days: set[dt.date] = field(default_factory=set)


class IngestionRunner:
    """Runs the bronze-to-gold pipeline for landed batches, idempotently."""

    def __init__(
        self,
        warehouse: Warehouse,
        registry: ContractRegistry,
        *,
        batches: BatchRegistry | None = None,
        dq_store: DQStore | None = None,
    ) -> None:
        self._warehouse = warehouse
        self._registry = registry
        self._batches = batches or BatchRegistry(warehouse)
        self._dq_store = dq_store or DQStore(warehouse)
        self._bronze = BronzeLoader(warehouse)
        self._gate = DataQualityGate()
        self._silver = SilverConformer(warehouse, registry, self._dq_store)
        self._gold = GoldBuilder(warehouse)
        self._panel = PanelBuilder(warehouse)

    @property
    def batch_registry(self) -> BatchRegistry:
        """The registry this runner writes to. Freshness and the API read it."""
        return self._batches

    @property
    def dq_store(self) -> DQStore:
        """Where DQ findings land. The admin panel reads it."""
        return self._dq_store

    # -------------------------------------------------------------- ingestion --
    def ingest(self, batch: LandedBatch, *, sim_time: dt.datetime) -> IngestResult:
        """Land one batch. Silver and gold are rebuilt immediately for its window."""
        results = self.ingest_many([batch], sim_time=sim_time)
        return results[0]

    def ingest_many(
        self, batches: list[LandedBatch], *, sim_time: dt.datetime
    ) -> list[IngestResult]:
        """Land a group of batches, then rebuild each touched window exactly once."""
        results: list[IngestResult] = []
        pending: dict[str, _Pending] = {}
        for batch in batches:
            result = self._land(batch, sim_time=sim_time)
            results.append(result)
            if result.accepted:
                dirty = pending.setdefault(result.source_id, _Pending())
                dirty.periods.update(result.periods)
                dirty.days.update(affected_days(tuple(result.periods)))

        rebuilt_days: set[dt.date] = set()
        for source_id, dirty in sorted(pending.items()):
            self._silver.rebuild(source_id, sorted(dirty.periods))
            rebuilt_days.update(dirty.days)
        if rebuilt_days:
            self._gold.rebuild(sorted(rebuilt_days))
            self._panel.rebuild_panel(sorted(rebuilt_days))

        # ``IngestResult`` is frozen, as every model at a boundary here is, so the
        # landed event is attached by rebuilding the result rather than by mutating it.
        return [
            result.model_copy(update={"event": self._emit(result, sim_time)})
            if result.accepted
            else result
            for result in results
        ]

    # ------------------------------------------------------------------ land --
    def _land(self, batch: LandedBatch, *, sim_time: dt.datetime) -> IngestResult:
        """Bronze plus DQ for one batch. Silver and gold happen in the group pass."""
        manifest = batch.manifest
        contract = self._registry.source(manifest.source_id)
        periods = list(manifest.covers.periods)

        if self._batches.is_known(manifest.source_id, manifest.batch_id):
            logger.info(
                "ingest.duplicate_batch",
                source_id=manifest.source_id,
                batch_id=manifest.batch_id,
            )
            return IngestResult(
                source_id=manifest.source_id,
                batch_id=manifest.batch_id,
                status="skipped_duplicate",
                periods=periods,
                rows_delivered=manifest.row_count,
                detail="batch id already in the registry; nothing was changed",
            )

        delivered = batch.read(contract)
        load = self._bronze.load(
            contract,
            delivered,
            manifest,
            sim_time=sim_time,
            source_file=batch.data_path.name,
        )
        rejected = contract.schema_spec.drift_policy == "reject_batch" and bool(load.drift)
        dq_results, quarantine = self._gate.evaluate(
            contract, load.frame, manifest.batch_id, coercion_failures=load.coercion_failures
        )
        if rejected:
            # A rejected batch still lands in bronze — bronze records what arrived, it
            # does not judge it — so every one of its rows is quarantined instead, and
            # the silver rebuild's anti-join keeps the whole delivery out of the marts.
            quarantine.append(
                QuarantineRecord(
                    source_id=contract.source_id,
                    batch_id=manifest.batch_id,
                    rule="drift:reject_batch",
                    reason="the contract's drift policy rejects any shape change",
                    row_count=load.rows,
                    row_hashes=load.frame["_row_hash"].astype(str).tolist(),
                )
            )
        self._dq_store.persist(dq_results, quarantine, load.drift)

        held = sum(record.row_count for record in quarantine)
        status = _status_for(load.rows, held, rejected=rejected)
        self._batches.record(
            manifest,
            status=status,
            rows_landed=load.rows,
            rows_quarantined=held,
            ingested_at=sim_time,
        )
        return IngestResult(
            source_id=manifest.source_id,
            batch_id=manifest.batch_id,
            status=status,
            periods=periods,
            rows_delivered=manifest.row_count,
            rows_landed=load.rows,
            rows_quarantined=held,
            dq_results=dq_results,
            drift=load.drift,
            quarantine=quarantine,
            detail=(
                "batch rejected: the contract's drift policy forbids a shape change"
                if rejected
                else ""
            ),
        )

    def _emit(self, result: IngestResult, sim_time: dt.datetime) -> DataLandedEvent:
        """Close the watermark and wake **only** the KPIs this source feeds."""
        states = self._batches.advance(result.source_id, result.periods, result.batch_id, sim_time)
        woken = [contract.kpi.id for contract in self._registry.kpis_depending_on(result.source_id)]
        event = DataLandedEvent(
            source_id=result.source_id,
            batch_id=result.batch_id,
            periods=result.periods,
            affected_days=affected_days(tuple(result.periods)),
            watermark_rewound=any(state.rewound for state in states),
            wakes_kpis=woken,
            received_at=sim_time,
        )
        logger.info(
            "ingest.landed",
            source_id=result.source_id,
            batch_id=result.batch_id,
            rows=result.rows_landed,
            quarantined=result.rows_quarantined,
            rewound=event.watermark_rewound,
            wakes=woken,
        )
        return event

    def ensure_tables(self) -> None:
        """Re-create the metadata tables. Called after a reset drops the schemas."""
        BatchRegistry.create_tables(self._warehouse)
        DQStore.create_tables(self._warehouse)

    # ----------------------------------------------------------------- spine --
    def build_calendar(self, start: dt.date, end: dt.date) -> int:
        """Materialise the calendar spine. Run once after the historical load."""
        return self._panel.build_calendar(start, end)


def _status_for(rows: int, quarantined: int, *, rejected: bool) -> BatchStatus:
    """The batch's outcome, from what actually happened to its rows."""
    if rejected:
        return "rejected"
    if rows == 0:
        return "empty"
    return "quarantined" if quarantined else "ingested"
