"""The `SourceProjector` interface and the container its outputs travel in.

A projector answers one question: *what would this system have recorded?* It reads the
L3 truth and produces rows in exactly the shape its source contract declares — same
grain, same columns, same types. That correspondence is checked at generation time, so
a projector that drifts from its contract fails immediately rather than at ingestion.

WHY projection is separate from defect injection: the projection is what the system
*legitimately* sees given its design (a weekly aggregator genuinely cannot report
daily; a T+2 extract genuinely lags). Defects (L5) are what goes *wrong* on top of
that. Keeping them apart means the ground truth for "what should this feed contain"
is always available, which is what makes a defect detectable rather than merely present.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.datagen.events.ledger import EventLedger
from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.simulate import Simulator
from insight_copilot.errors import SimulationError


@dataclass
class ProjectionContext:
    """Everything a projector may read. Read-only by convention."""

    simulator: Simulator
    panel: SimulationPanel
    ledger: EventLedger

    @property
    def config(self):  # type: ignore[no-untyped-def]  # returns WorldConfig
        """The world constants."""
        return self.simulator.config

    @property
    def calendar(self):  # type: ignore[no-untyped-def]  # returns Calendar
        """The date axis and calendar-derived effects."""
        return self.simulator.calendar

    @property
    def catalog(self):  # type: ignore[no-untyped-def]  # returns ProductCatalog
        """The SKU master."""
        return self.simulator.catalog


@dataclass
class SourceFrames:
    """Every source's rows, keyed by source id.

    A single container rather than eleven variables so the defect catalog can be
    applied uniformly and so a cross-source reconciliation can reach both sides.
    """

    frames: dict[str, pd.DataFrame] = field(default_factory=dict)

    def __getitem__(self, source_id: str) -> pd.DataFrame:
        try:
            return self.frames[source_id]
        except KeyError as exc:
            raise SimulationError(
                f"no rows projected for source {source_id!r}",
                detail=f"available: {', '.join(sorted(self.frames))}",
            ) from exc

    def __setitem__(self, source_id: str, frame: pd.DataFrame) -> None:
        self.frames[source_id] = frame

    def __contains__(self, source_id: str) -> bool:
        return source_id in self.frames

    def copy(self) -> SourceFrames:
        """A shallow copy with independent frames, so an injector cannot mutate ours."""
        return SourceFrames({key: value.copy() for key, value in self.frames.items()})

    @property
    def source_ids(self) -> list[str]:
        """Sources present, sorted."""
        return sorted(self.frames)

    def row_counts(self) -> dict[str, int]:
        """Rows per source, for the generation manifest."""
        return {key: len(value) for key, value in sorted(self.frames.items())}


class SourceProjector(ABC):
    """Projects the L3 truth into one source system's view of it."""

    def __init__(self, contract: SourceContract) -> None:
        self.contract = contract

    @property
    def source_id(self) -> str:
        """The id this projector fills."""
        return self.contract.source_id

    @abstractmethod
    def project(self, context: ProjectionContext) -> pd.DataFrame:
        """Produce the rows this system would have recorded."""

    def validate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Check the projection against its own source contract.

        Columns must match the declared schema exactly — no extras, none missing.
        A projector that quietly adds a column would sail through ingestion and then
        surprise the DQ layer, which is precisely the class of bug the source contract
        exists to prevent.
        """
        declared = set(self.contract.schema_spec.columns)
        produced = set(frame.columns)
        missing = declared - produced
        extra = produced - declared
        if missing or extra:
            raise SimulationError(
                f"{self.source_id}: projection disagrees with its source contract",
                detail=f"missing={sorted(missing)} unexpected={sorted(extra)}",
            )
        return frame[list(self.contract.schema_spec.columns)]

    def run(self, context: ProjectionContext) -> pd.DataFrame:
        """Project and validate."""
        return self.validate(self.project(context))
