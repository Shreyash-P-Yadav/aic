"""The `DefectInjector` interface and the catalog that registers them.

Two kinds of injector live here and the distinction is deliberate:

* **Transformational** injectors change the projected rows — a unit switches from
  paise to rupees, a column is renamed, a batch is duplicated.
* **Structural** injectors change nothing, because the pathology is already realised
  by the design. Different refresh cadences are in the source contracts' cron
  expressions; fiscal-versus-ISO calendars are in the KPI contracts. Injecting them
  again would be inventing a defect on top of one that already exists.

Both kinds implement `detect()`, and that is what the P4 gate actually asserts. A
defect that is present but undetectable is worthless — it would flatter the engine by
existing without ever being caught — so the catalog's contract is *present AND
detectable*, not merely present.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames
from insight_copilot.errors import SimulationError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


def _catalog_order(code: str) -> tuple[int, str]:
    """Sort key for a catalog code. ``P6a`` follows ``P6`` and precedes ``P7``."""
    digits = "".join(character for character in code[1:] if character.isdigit())
    suffix = code[1 + len(digits) :]
    return int(digits), suffix


@dataclass(frozen=True)
class DefectEvidence:
    """The result of looking for a defect in the data."""

    code: str
    present: bool
    detail: str
    metrics: dict[str, float] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.present


class DefectInjector(ABC):
    """One pathology from the catalog, individually toggleable."""

    code: ClassVar[str]
    """`P1` .. `P30`, matching DataLayer §7."""

    title: ClassVar[str]
    complexity: ClassVar[str]
    """The brief complexity this defect exercises."""

    exercises: ClassVar[str]
    """The component that has to cope with it."""

    demo_moment: ClassVar[str]
    """Where a judge would see it. "silent" for the ones that only harden the system."""

    structural: ClassVar[bool] = False
    """True when the design already realises this pathology and there is nothing to inject."""

    enabled: bool = True

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        """Transform the projected rows. Structural injectors leave them untouched."""
        del context
        return frames

    @abstractmethod
    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        """Look for this defect in the data and report what was found."""

    def _found(self, detail: str, **metrics: float) -> DefectEvidence:
        """Helper: the defect is present."""
        return DefectEvidence(code=self.code, present=True, detail=detail, metrics=metrics)

    def _missing(self, detail: str, **metrics: float) -> DefectEvidence:
        """Helper: the defect is absent, which is a failure."""
        return DefectEvidence(code=self.code, present=False, detail=detail, metrics=metrics)


class DefectCatalog:
    """Every registered pathology, in catalog order."""

    def __init__(self, injectors: list[DefectInjector]) -> None:
        codes = [injector.code for injector in injectors]
        duplicates = {code for code in codes if codes.count(code) > 1}
        if duplicates:
            raise SimulationError(f"duplicate defect codes: {sorted(duplicates)}")
        self._injectors = sorted(injectors, key=lambda item: _catalog_order(item.code))

    def __len__(self) -> int:
        return len(self._injectors)

    def __iter__(self):  # type: ignore[no-untyped-def]  # Iterator[DefectInjector]
        return iter(self._injectors)

    @property
    def codes(self) -> list[str]:
        """Catalog codes in order."""
        return [injector.code for injector in self._injectors]

    def get(self, code: str) -> DefectInjector:
        """One injector by code."""
        for injector in self._injectors:
            if injector.code == code:
                return injector
        raise SimulationError(f"unknown defect {code!r}", detail=f"known: {self.codes}")

    def enabled_injectors(self) -> list[DefectInjector]:
        """Only the injectors currently switched on."""
        return [injector for injector in self._injectors if injector.enabled]

    def apply_all(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        """Apply every enabled injector in catalog order.

        Order matters and it is the catalog's: a unit change applied after a schema
        rename would target a column that no longer exists. Catalog order is also the
        order a reader of DataLayer §7 expects, so the two cannot drift.
        """
        result = frames
        for injector in self.enabled_injectors():
            if injector.structural:
                continue
            result = injector.apply(result, context)
            logger.debug("defect.applied", code=injector.code)
        return result

    def detect_all(
        self, frames: SourceFrames, context: ProjectionContext
    ) -> dict[str, DefectEvidence]:
        """Look for every defect. The P4 gate asserts all of them are found."""
        return {injector.code: injector.detect(frames, context) for injector in self._injectors}


def build_catalog() -> DefectCatalog:
    """The complete P1-P30 catalog."""
    from insight_copilot.datagen.defects import (
        analytical,
        arrival,
        evidence,
        quality,
        schema,
    )

    return DefectCatalog(
        [
            *arrival.INJECTORS,
            *schema.INJECTORS,
            *quality.INJECTORS,
            *analytical.INJECTORS,
            *evidence.INJECTORS,
        ]
    )
