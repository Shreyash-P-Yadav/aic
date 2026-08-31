"""The full data-generation pipeline: truth -> projection -> defects -> corpus.

One function so the CLI, the tests and the demo all build the same world in the same
order. The order is the layer order from the design and it matters:

1. **L0-L3** simulate the business under the event ledger.
2. **L4** project that truth into eleven source systems, each lossy in its own way.
3. **L5** inject the pathology catalog on top of the projections.
4. **L6** build the corpus from the ledger, then attach it as two more sources.

Defects are applied *after* projection because they are things that go wrong with a
feed, not properties of the feed's design. Keeping the two apart means "what should
this source contain" is always recoverable, which is what makes a defect detectable
rather than merely present.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.datagen.corpus.assemble import CorpusBuilder
from insight_copilot.datagen.corpus.frames import to_memo_frame, to_news_frame
from insight_copilot.datagen.corpus.models import Document
from insight_copilot.datagen.defects.base import DefectCatalog, build_catalog
from insight_copilot.datagen.events.build import build_full_ledger
from insight_copilot.datagen.events.effects import LedgerOverlay
from insight_copilot.datagen.events.ledger import EventLedger
from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames
from insight_copilot.datagen.projection.runner import (
    ReconciliationDelta,
    measure_reconciliations,
    project_all,
)
from insight_copilot.datagen.simulate import Simulator
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class GeneratedWorld:
    """Everything one generation run produced."""

    simulator: Simulator
    panel: SimulationPanel
    ledger: EventLedger
    frames: SourceFrames
    documents: list[Document]
    catalog: DefectCatalog
    reconciliations: list[ReconciliationDelta]
    context: ProjectionContext

    def row_counts(self) -> dict[str, int]:
        """Rows per source, plus the corpus."""
        counts = self.frames.row_counts()
        counts["_documents"] = len(self.documents)
        return counts


def generate_world(
    *,
    seed: int,
    registry: ContractRegistry | None = None,
    apply_defects: bool = True,
) -> GeneratedWorld:
    """Build the complete world: truth, sources, defects and corpus."""
    simulator = Simulator.from_defaults(seed)
    contracts = registry or ContractRegistry.from_directory(_contracts_dir())

    ledger = build_full_ledger(simulator.config, simulator.catalog, simulator.seeds)
    overlay = LedgerOverlay(
        ledger.events,
        config=simulator.config,
        catalog=simulator.catalog,
        cells=simulator.assortment,
        horizon_start=simulator.config.horizon.start,
    )
    panel = simulator.run(overlay)
    context = ProjectionContext(simulator=simulator, panel=panel, ledger=ledger)

    frames = project_all(context, contracts)

    documents = CorpusBuilder(simulator.config, ledger, simulator.seeds).build()
    frames["news_articles"] = to_news_frame(documents)
    frames["pricing_memos"] = to_memo_frame(documents)

    defects = build_catalog()
    if apply_defects:
        frames = defects.apply_all(frames, context)

    reconciliations = measure_reconciliations(frames)
    logger.info(
        "pipeline.done",
        sources=len(frames.source_ids),
        documents=len(documents),
        defects=len(defects),
    )
    return GeneratedWorld(
        simulator=simulator,
        panel=panel,
        ledger=ledger,
        frames=frames,
        documents=documents,
        catalog=defects,
        reconciliations=reconciliations,
        context=context,
    )


def _contracts_dir() -> Path:
    import insight_copilot.contracts as contracts_package

    return Path(contracts_package.__file__).resolve().parent


def documents_frame(documents: list[Document]) -> pd.DataFrame:
    """The whole corpus as one table, for the retrieval index and the fixtures."""
    return pd.DataFrame([document.model_dump(mode="json") for document in documents])
